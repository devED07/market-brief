"""Prices from Yahoo Finance (free, no key). Futures on Yahoo are delayed
about 10 minutes, which is fine for context and bias but not for entries."""

import json
import logging
import urllib.parse
import urllib.request
import warnings
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from .config import DATA_DIR
from .util import NEW_YORK, atomic_write_json

TOKYO = ZoneInfo("Asia/Tokyo")
LONDON = ZoneInfo("Europe/London")

# yfinance prints a lot of noise when a symbol hiccups; the app reports
# problems in its own words instead.
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
warnings.filterwarnings("ignore", module=r"yfinance(\.|$)")

SNAPS_CACHE_FILE = DATA_DIR / "snaps_cache.json"

LABELS = {
    "gold": "Gold",
    "us30": "US30",
    "us100": "US100",
    "dollar": "Dollar index",
    "treasury_10y": "10Y T-note",
    "vix": "VIX",
}


OANDA_HOSTS = {
    "practice": "https://api-fxpractice.oanda.com",
    "live": "https://api-fxtrade.oanda.com",
}


def _build_ohlc_series(times: list, opens: list[float], highs: list[float],
                       lows: list[float], closes: list[float],
                       source: str, label: str) -> pd.Series:
    """Build a UTC-sorted Close Series with aligned OHLC wick attrs."""
    if not times:
        raise ValueError(f"no {source} data for {label}")
    idx = pd.to_datetime(times, utc=True)
    df = pd.DataFrame({"Open": opens, "High": highs, "Low": lows, "Close": closes}, index=idx)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    s = df["Close"].dropna()
    if s.empty:
        raise ValueError(f"no {source} data for {label}")
    s.attrs["ohlc_open"] = df["Open"].reindex(s.index).fillna(s)
    s.attrs["ohlc_high"] = df["High"].reindex(s.index).fillna(s)
    s.attrs["ohlc_low"] = df["Low"].reindex(s.index).fillna(s)
    s.attrs["source"] = source
    return s


def fetch_oanda_series(instrument: str, api_key: str, env: str = "practice",
                       count: int = 3000, opener=None) -> pd.Series:
    """5-minute CFD midpoint candles from OANDA v20 REST API, indexed in UTC."""
    host = OANDA_HOSTS.get((env or "practice").lower(), OANDA_HOSTS["practice"])
    url = (
        f"{host}/v3/instruments/{urllib.parse.quote(instrument, safe='')}/candles"
        f"?granularity=M5&count={count}&price=M"
    )
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept-Datetime-Format": "RFC3339",
            "User-Agent": "market-brief/1.0",
        },
    )
    with (opener or urllib.request.urlopen)(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    times, opens, highs, lows, closes = [], [], [], [], []
    for c in payload.get("candles") or []:
        mid = c.get("mid") or {}
        ts = c.get("time")
        if not ts or not all(k in mid for k in ("o", "h", "l", "c")):
            continue
        times.append(ts)
        opens.append(float(mid["o"]))
        highs.append(float(mid["h"]))
        lows.append(float(mid["l"]))
        closes.append(float(mid["c"]))
    return _build_ohlc_series(times, opens, highs, lows, closes, "oanda", instrument)


def fetch_twelvedata_series(symbol: str, api_key: str, outputsize: int = 3000,
                            opener=None) -> pd.Series:
    """5-minute spot/forex candles from Twelve Data /time_series, indexed in UTC."""
    url = (
        "https://api.twelvedata.com/time_series"
        f"?symbol={urllib.parse.quote(symbol, safe='')}"
        f"&interval=5min&outputsize={outputsize}&timezone=UTC&order=asc"
        f"&apikey={urllib.parse.quote(api_key, safe='')}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "market-brief/1.0"})
    with (opener or urllib.request.urlopen)(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    if payload.get("status") == "error":
        raise ValueError(payload.get("message") or f"Twelve Data error for {symbol}")

    times, opens, highs, lows, closes = [], [], [], [], []
    for v in payload.get("values") or []:
        ts = v.get("datetime")
        if not ts or not all(k in v for k in ("open", "high", "low", "close")):
            continue
        times.append(ts)
        opens.append(float(v["open"]))
        highs.append(float(v["high"]))
        lows.append(float(v["low"]))
        closes.append(float(v["close"]))
    return _build_ohlc_series(times, opens, highs, lows, closes, "twelvedata", symbol)


def fetch_series(symbol: str) -> pd.Series:
    """5-minute closes for the last ~10 days (7d fallback), indexed in UTC."""
    import yfinance as yf  # imported here so demo mode works without it

    # yfinance switches its own warnings back on when imported; hide them again.
    warnings.filterwarnings("ignore", module=r"yfinance")

    ticker = yf.Ticker(symbol)
    df = None
    for period in ("10d", "7d"):
        try:
            cand = ticker.history(period=period, interval="5m", auto_adjust=False)
            if cand is not None and not cand.empty and "Close" in cand:
                df = cand
                break
        except Exception:
            if period == "7d":
                raise
    if df is None or df.empty or "Close" not in df:
        raise ValueError(f"no data for {symbol}")
    df = df.copy()
    df.index = pd.to_datetime(df.index, utc=True)
    df = df.sort_index()
    s = df["Close"].dropna()
    if "Open" in df:
        s.attrs["ohlc_open"] = df["Open"].reindex(s.index).fillna(s)
    if "High" in df:
        s.attrs["ohlc_high"] = df["High"].reindex(s.index).fillna(s)
    if "Low" in df:
        s.attrs["ohlc_low"] = df["Low"].reindex(s.index).fillna(s)
    s.attrs["source"] = "yahoo"
    return s


def _ohlc_for(series: pd.Series, target: pd.Series | None = None) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Return (Open, High, Low) Series aligned to target/series, falling back to Close."""
    ref = target if target is not None else series
    attrs = getattr(series, "attrs", {}) or {}

    def _pick(name: str) -> pd.Series:
        col = attrs.get(name)
        if isinstance(col, pd.Series) and not col.empty:
            return col.reindex(ref.index).fillna(ref)
        return ref

    return _pick("ohlc_open"), _pick("ohlc_high"), _pick("ohlc_low")


def price_at(series: pd.Series, when: datetime, max_gap_min: int = 20) -> float | None:
    """Price at a moment in time = close of the 5-min bar that ends then.
    Returns None if the nearest bar is too old (market closed, gap)."""
    if series is None or series.empty:
        return None
    target = pd.Timestamp(when - timedelta(minutes=5))
    sub = series.loc[:target]
    if sub.empty:
        return None
    if (target - sub.index[-1]) > pd.Timedelta(minutes=max_gap_min):
        return None
    return float(sub.iloc[-1])


def pct(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or a == 0:
        return None
    return (b - a) / a * 100.0


def _hl_with_time(day_s: pd.Series, hi_s: pd.Series | None = None,
                  lo_s: pd.Series | None = None) -> tuple[float | None, str, float | None, str]:
    h_src = day_s if hi_s is None else hi_s
    l_src = day_s if lo_s is None else lo_s
    if h_src.empty or l_src.empty:
        return None, "", None, ""
    return (
        float(h_src.max()),
        h_src.idxmax().to_pydatetime().isoformat(),
        float(l_src.min()),
        l_src.idxmin().to_pydatetime().isoformat(),
    )


def _session_day_splits(day_s: pd.Series, day_ny: pd.DatetimeIndex,
                        hi_s: pd.Series | None = None,
                        lo_s: pd.Series | None = None) -> dict[str, float | str | None]:
    h_src = day_s if hi_s is None else hi_s
    l_src = day_s if lo_s is None else lo_s
    tok = day_s.index.tz_convert(TOKYO)
    tok_m = tok.hour * 60 + tok.minute
    lon = day_s.index.tz_convert(LONDON)
    lon_m = lon.hour * 60 + lon.minute
    ny_m = day_ny.hour * 60 + day_ny.minute

    m_asia = (tok_m >= 9 * 60) & (tok_m < 15 * 60)
    m_lon = (lon_m >= 8 * 60 + 30) & (lon_m < 16 * 60 + 30)
    m_ny = (ny_m >= 9 * 60 + 30) & (ny_m < 16 * 60)

    asia_h, asia_h_t, asia_l, asia_l_t = _hl_with_time(day_s[m_asia], h_src[m_asia], l_src[m_asia])
    lon_h, lon_h_t, lon_l, lon_l_t = _hl_with_time(day_s[m_lon], h_src[m_lon], l_src[m_lon])
    ny_h, ny_h_t, ny_l, ny_l_t = _hl_with_time(day_s[m_ny], h_src[m_ny], l_src[m_ny])
    return {
        "asia_h": asia_h,
        "asia_h_t": asia_h_t,
        "asia_l": asia_l,
        "asia_l_t": asia_l_t,
        "london_h": lon_h,
        "london_h_t": lon_h_t,
        "london_l": lon_l,
        "london_l_t": lon_l_t,
        "ny_h": ny_h,
        "ny_h_t": ny_h_t,
        "ny_l": ny_l,
        "ny_l_t": ny_l_t,
    }


def _build_day_dict(day_s: pd.Series, day_ny: pd.DatetimeIndex, d: pd.Timestamp,
                    is_today: bool = False, op_s: pd.Series | None = None,
                    hi_s: pd.Series | None = None, lo_s: pd.Series | None = None) -> dict:
    hi, hi_t, lo, lo_t = _hl_with_time(day_s, hi_s, lo_s)
    op = float(op_s.iloc[0]) if op_s is not None and not op_s.empty else float(day_s.iloc[0])
    cl = float(day_s.iloc[-1])
    row: dict = {
        "date": d.strftime("%Y-%m-%d"),
        "label": d.strftime("%a, %b %d").replace(" 0", " "),
        "full_label": d.strftime("%A, %b %d").replace(" 0", " "),
        "is_today": is_today,
        "open": op,
        "high": hi,
        "high_t": hi_t,
        "low": lo,
        "low_t": lo_t,
        "close": cl,
        "chg_pct": pct(op, cl),
        "range_pct": round((hi - lo) / op * 100.0, 2) if (hi is not None and lo is not None and op > 0) else None,
    }
    row.update(_session_day_splits(day_s, day_ny, hi_s, lo_s))
    return row


def daily_levels(series: pd.Series, days: int = 5) -> list[dict]:
    """Completed NY futures trading-day highs, lows, closes, and session levels (newest first)."""
    if series is None or series.empty:
        return []
    sorted_s = series.sort_index()
    op_s, hi_s, lo_s = _ohlc_for(series, sorted_s)
    ny_idx = sorted_s.index.tz_convert(NEW_YORK)
    sess_dates = (ny_idx + pd.Timedelta(hours=6)).normalize()
    uniq_dates = sess_dates.unique()
    if len(uniq_dates) < 2:
        return []
    completed = list(uniq_dates[-(days + 1):-1])[::-1]

    out: list[dict] = []
    for d in completed:
        mask = sess_dates == d
        day_s = sorted_s[mask]
        if day_s.empty:
            continue
        out.append(_build_day_dict(day_s, ny_idx[mask], d, is_today=False,
                                   op_s=op_s[mask], hi_s=hi_s[mask], lo_s=lo_s[mask]))
    return out


def current_day_levels(series: pd.Series) -> dict | None:
    """Developing NY futures trading day levels (Today)."""
    if series is None or series.empty:
        return None
    sorted_s = series.sort_index()
    op_s, hi_s, lo_s = _ohlc_for(series, sorted_s)
    ny_idx = sorted_s.index.tz_convert(NEW_YORK)
    sess_dates = (ny_idx + pd.Timedelta(hours=6)).normalize()
    uniq_dates = sess_dates.unique()
    if len(uniq_dates) == 0:
        return None
    d = uniq_dates[-1]
    mask = sess_dates == d
    day_s = sorted_s[mask]
    if day_s.empty:
        return None
    return _build_day_dict(day_s, ny_idx[mask], d, is_today=True,
                           op_s=op_s[mask], hi_s=hi_s[mask], lo_s=lo_s[mask])


def session_levels(series: pd.Series) -> dict:
    """Live session key levels (Today, Asia/London/NY, PDH/PDL/PDC, and 5-day swing)."""
    if series is None or series.empty:
        return {}
    sorted_s = series.sort_index()
    op_s, hi_s, lo_s = _ohlc_for(series, sorted_s)
    ny_idx = sorted_s.index.tz_convert(NEW_YORK)
    sess_dates = (ny_idx + pd.Timedelta(hours=6)).normalize()
    uniq_dates = sess_dates.unique()
    if len(uniq_dates) == 0:
        return {}

    cur_mask = sess_dates == uniq_dates[-1]
    cur_s = sorted_s[cur_mask]
    out: dict[str, float | None] = {
        "today_open": float(op_s[cur_mask].iloc[0]),
        "today_high": float(hi_s[cur_mask].max()),
        "today_low": float(lo_s[cur_mask].min()),
    }
    out.update(_session_day_splits(cur_s, ny_idx[cur_mask], hi_s[cur_mask], lo_s[cur_mask]))

    if len(uniq_dates) >= 2:
        prev_mask = sess_dates == uniq_dates[-2]
        prev_s = sorted_s[prev_mask]
        prev_splits = _session_day_splits(prev_s, ny_idx[prev_mask], hi_s[prev_mask], lo_s[prev_mask])
        out.update({
            "pdh": float(hi_s[prev_mask].max()),
            "pdl": float(lo_s[prev_mask].min()),
            "pdc": float(prev_s.iloc[-1]),
            "prev_asia_h": prev_splits["asia_h"],
            "prev_asia_l": prev_splits["asia_l"],
            "prev_london_h": prev_splits["london_h"],
            "prev_london_l": prev_splits["london_l"],
            "prev_ny_h": prev_splits["ny_h"],
            "prev_ny_l": prev_splits["ny_l"],
        })
        wk_mask = sess_dates.isin(uniq_dates[-6:-1])
        if wk_mask.any():
            out["week_h"] = float(hi_s[wk_mask].max())
            out["week_l"] = float(lo_s[wk_mask].min())
    return out


def snapshot(series: pd.Series, now: datetime) -> dict:
    sorted_s = series.sort_index()
    op_s, hi_s, lo_s = _ohlc_for(series, sorted_s)
    last_time = sorted_s.index[-1].to_pydatetime()
    last = float(sorted_s.iloc[-1])

    def ago(minutes: int, max_gap_min: int) -> float | None:
        t = pd.Timestamp(last_time - timedelta(minutes=minutes))
        sub = sorted_s.loc[:t]
        if sub.empty:
            return None
        if (t - sub.index[-1]) > pd.Timedelta(minutes=max_gap_min):
            return None
        return float(sub.iloc[-1])

    ny_idx = sorted_s.index.tz_convert(NEW_YORK)
    sess_dates = (ny_idx + pd.Timedelta(hours=6)).normalize()
    uniq_dates = sess_dates.unique()
    last_5 = uniq_dates[-5:]
    window = sorted_s[sess_dates.isin(last_5)]
    avg_5d = float(window.mean()) if len(window) > 50 else None

    pdh = pdl = range_used = None
    if len(uniq_dates) >= 2:
        prev_mask = sess_dates == uniq_dates[-2]
        if prev_mask.any():
            pdh = float(hi_s[prev_mask].max())
            pdl = float(lo_s[prev_mask].min())
        today_mask = sess_dates == uniq_dates[-1]
        prior_ranges = []
        for d in uniq_dates[-6:-1]:
            dm = sess_dates == d
            if dm.sum() >= 12 and float(op_s[dm].iloc[0]) > 0:
                prior_ranges.append((float(hi_s[dm].max()) - float(lo_s[dm].min())) / float(op_s[dm].iloc[0]) * 100.0)
        if today_mask.any() and prior_ranges and float(op_s[today_mask].iloc[0]) > 0:
            today_rng = (float(hi_s[today_mask].max()) - float(lo_s[today_mask].min())) / float(op_s[today_mask].iloc[0]) * 100.0
            avg_rng = sum(prior_ranges) / len(prior_ranges)
            if avg_rng > 0:
                range_used = round(today_rng / avg_rng, 2)

    return {
        "last": last,
        "last_time": last_time,
        "vs_5d": pct(avg_5d, last),
        "stale_min": max(0, int((now - last_time).total_seconds() // 60)),
        "cached": False,
        "chg_30m": pct(ago(30, max_gap_min=35), last),
        "chg_4h": pct(ago(240, max_gap_min=90), last),
        "chg_24h": pct(ago(1440, max_gap_min=72 * 60), last),
        "pdh": pdh,
        "pdl": pdl,
        "range_used": range_used,
        "source": (getattr(series, "attrs", {}) or {}).get("source", "yahoo"),
        "levels_5d": daily_levels(series, days=5),
        "today_levels": current_day_levels(series),
        "session_levels": session_levels(series),
    }


def save_snaps_cache(snaps: dict, now: datetime) -> None:
    """Persist latest price snapshots so hosted runs survive single-run Yahoo glitches."""
    serialized = {}
    for key, s in snaps.items():
        if not s or "last_time" not in s:
            continue
        item = dict(s)
        lt = item["last_time"]
        item["last_time"] = lt.isoformat() if isinstance(lt, datetime) else str(lt)
        serialized[key] = item
    if serialized:
        atomic_write_json(SNAPS_CACHE_FILE, {"saved": now.isoformat(), "snaps": serialized})


def load_snaps_cache(now: datetime, max_age_min: int = 120, weekend: bool = False) -> dict:
    """Restore cached snapshots whose last bar is still within TTL."""
    try:
        raw = json.loads(SNAPS_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    entries = raw.get("snaps", raw) if isinstance(raw, dict) else {}
    limit_min = 72 * 60 if weekend else max_age_min
    out = {}
    for key, s in entries.items():
        if not isinstance(s, dict) or "last_time" not in s:
            continue
        try:
            lt = datetime.fromisoformat(s["last_time"])
            if lt.tzinfo is None:
                lt = lt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        age_min = (now - lt).total_seconds() / 60
        if age_min <= limit_min:
            restored = dict(s)
            restored["last_time"] = lt
            restored["stale_min"] = max(0, int((now - lt).total_seconds() // 60))
            restored["cached"] = True
            out[key] = restored
    return out


def fetch_all(symbols: dict[str, str], now: datetime | None = None,
              oanda_key: str = "", oanda_env: str = "practice",
              oanda_symbols: dict[str, str] | None = None,
              twelvedata_key: str = "",
              twelvedata_symbols: dict[str, str] | None = None) -> tuple[dict, dict, list[str]]:
    """Returns (series_by_key, snapshot_by_key, problems)."""
    now = now or datetime.now(timezone.utc)
    series, snaps, problems = {}, {}, []
    for key, symbol in symbols.items():
        s = None
        oanda_sym = (oanda_symbols or {}).get(key, "")
        td_sym = (twelvedata_symbols or {}).get(key, "")
        if oanda_key and oanda_sym:
            try:
                s = fetch_oanda_series(oanda_sym, oanda_key, env=oanda_env)
            except Exception as exc:
                problems.append(
                    f"{LABELS.get(key, key)} OANDA ({oanda_sym}): {exc.__class__.__name__}, falling back"
                )
        if s is None and twelvedata_key and td_sym:
            try:
                s = fetch_twelvedata_series(td_sym, twelvedata_key)
            except Exception as exc:
                problems.append(
                    f"{LABELS.get(key, key)} Twelve Data ({td_sym}): {exc.__class__.__name__}, falling back to {symbol}"
                )
        if s is None:
            try:
                s = fetch_series(symbol)
            except Exception as exc:
                problems.append(f"{LABELS.get(key, key)} ({symbol}): {exc.__class__.__name__}")
                continue
        series[key] = s
        snaps[key] = snapshot(s, now)
    return series, snaps, problems
