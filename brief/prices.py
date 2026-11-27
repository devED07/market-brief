"""Prices from Yahoo Finance (free, no key). Futures on Yahoo are delayed
about 10 minutes, which is fine for context and bias but not for entries."""

import json
import logging
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
    s = df["Close"].dropna()
    s.index = pd.to_datetime(s.index, utc=True)
    return s.sort_index()


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


def _hl_with_time(sub: pd.Series) -> tuple[float | None, str, float | None, str]:
    if sub.empty:
        return None, "", None, ""
    return (
        float(sub.max()),
        sub.idxmax().to_pydatetime().isoformat(),
        float(sub.min()),
        sub.idxmin().to_pydatetime().isoformat(),
    )


def _session_day_splits(day_s: pd.Series, day_ny: pd.DatetimeIndex) -> dict[str, float | str | None]:
    tok = day_s.index.tz_convert(TOKYO)
    tok_m = tok.hour * 60 + tok.minute
    lon = day_s.index.tz_convert(LONDON)
    lon_m = lon.hour * 60 + lon.minute
    ny_m = day_ny.hour * 60 + day_ny.minute

    asia_h, asia_h_t, asia_l, asia_l_t = _hl_with_time(day_s[(tok_m >= 9 * 60) & (tok_m < 15 * 60)])
    lon_h, lon_h_t, lon_l, lon_l_t = _hl_with_time(day_s[(lon_m >= 8 * 60) & (lon_m < 16 * 60 + 30)])
    ny_h, ny_h_t, ny_l, ny_l_t = _hl_with_time(day_s[(ny_m >= 8 * 60) & (ny_m < 17 * 60)])
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
                    is_today: bool = False) -> dict:
    hi, hi_t, lo, lo_t = _hl_with_time(day_s)
    op = float(day_s.iloc[0])
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
    row.update(_session_day_splits(day_s, day_ny))
    return row


def daily_levels(series: pd.Series, days: int = 5) -> list[dict]:
    """Completed NY futures trading-day highs, lows, closes, and session levels (newest first)."""
    if series is None or series.empty:
        return []
    series = series.sort_index()
    ny_idx = series.index.tz_convert(NEW_YORK)
    sess_dates = (ny_idx + pd.Timedelta(hours=6)).normalize()
    uniq_dates = sess_dates.unique()
    if len(uniq_dates) < 2:
        return []
    completed = list(uniq_dates[-(days + 1):-1])[::-1]

    out: list[dict] = []
    for d in completed:
        mask = sess_dates == d
        day_s = series[mask]
        if day_s.empty:
            continue
        out.append(_build_day_dict(day_s, ny_idx[mask], d, is_today=False))
    return out


def current_day_levels(series: pd.Series) -> dict | None:
    """Developing NY futures trading day levels (Today)."""
    if series is None or series.empty:
        return None
    series = series.sort_index()
    ny_idx = series.index.tz_convert(NEW_YORK)
    sess_dates = (ny_idx + pd.Timedelta(hours=6)).normalize()
    uniq_dates = sess_dates.unique()
    if len(uniq_dates) == 0:
        return None
    d = uniq_dates[-1]
    mask = sess_dates == d
    day_s = series[mask]
    if day_s.empty:
        return None
    return _build_day_dict(day_s, ny_idx[mask], d, is_today=True)


def session_levels(series: pd.Series) -> dict:
    """Live session key levels (Today, Asia/London/NY, PDH/PDL/PDC, and 5-day swing)."""
    if series is None or series.empty:
        return {}
    series = series.sort_index()
    ny_idx = series.index.tz_convert(NEW_YORK)
    sess_dates = (ny_idx + pd.Timedelta(hours=6)).normalize()
    uniq_dates = sess_dates.unique()
    if len(uniq_dates) == 0:
        return {}

    cur_mask = sess_dates == uniq_dates[-1]
    cur_s = series[cur_mask]
    out: dict[str, float | None] = {
        "today_open": float(cur_s.iloc[0]),
        "today_high": float(cur_s.max()),
        "today_low": float(cur_s.min()),
    }
    out.update(_session_day_splits(cur_s, ny_idx[cur_mask]))

    if len(uniq_dates) >= 2:
        prev_mask = sess_dates == uniq_dates[-2]
        prev_s = series[prev_mask]
        prev_splits = _session_day_splits(prev_s, ny_idx[prev_mask])
        out.update({
            "pdh": float(prev_s.max()),
            "pdl": float(prev_s.min()),
            "pdc": float(prev_s.iloc[-1]),
            "prev_asia_h": prev_splits["asia_h"],
            "prev_asia_l": prev_splits["asia_l"],
            "prev_london_h": prev_splits["london_h"],
            "prev_london_l": prev_splits["london_l"],
            "prev_ny_h": prev_splits["ny_h"],
            "prev_ny_l": prev_splits["ny_l"],
        })
        wk_s = series[sess_dates.isin(uniq_dates[-6:-1])]
        if not wk_s.empty:
            out["week_h"] = float(wk_s.max())
            out["week_l"] = float(wk_s.min())
    return out


def snapshot(series: pd.Series, now: datetime) -> dict:
    series = series.sort_index()
    last_time = series.index[-1].to_pydatetime()
    last = float(series.iloc[-1])

    def ago(minutes: int, max_gap_min: int) -> float | None:
        t = pd.Timestamp(last_time - timedelta(minutes=minutes))
        sub = series.loc[:t]
        if sub.empty:
            return None
        if (t - sub.index[-1]) > pd.Timedelta(minutes=max_gap_min):
            return None
        return float(sub.iloc[-1])

    ny_idx = series.index.tz_convert(NEW_YORK)
    sess_dates = (ny_idx + pd.Timedelta(hours=6)).normalize()
    uniq_dates = sess_dates.unique()
    last_5 = uniq_dates[-5:]
    window = series[sess_dates.isin(last_5)]
    avg_5d = float(window.mean()) if len(window) > 50 else None

    pdh = pdl = range_used = None
    if len(uniq_dates) >= 2:
        prev_day = series[sess_dates == uniq_dates[-2]]
        if not prev_day.empty:
            pdh = float(prev_day.max())
            pdl = float(prev_day.min())
        today_bars = series[sess_dates == uniq_dates[-1]]
        prior_ranges = []
        for d in uniq_dates[-6:-1]:
            day_s = series[sess_dates == d]
            if len(day_s) >= 12 and float(day_s.iloc[0]) > 0:
                prior_ranges.append((float(day_s.max()) - float(day_s.min())) / float(day_s.iloc[0]) * 100.0)
        if not today_bars.empty and prior_ranges and float(today_bars.iloc[0]) > 0:
            today_rng = (float(today_bars.max()) - float(today_bars.min())) / float(today_bars.iloc[0]) * 100.0
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


def fetch_all(symbols: dict[str, str], now: datetime | None = None) -> tuple[dict, dict, list[str]]:
    """Returns (series_by_key, snapshot_by_key, problems)."""
    now = now or datetime.now(timezone.utc)
    series, snaps, problems = {}, {}, []
    for key, symbol in symbols.items():
        try:
            s = fetch_series(symbol)
            series[key] = s
            snaps[key] = snapshot(s, now)
        except Exception as exc:
            problems.append(f"{LABELS.get(key, key)} ({symbol}): {exc.__class__.__name__}")
    return series, snaps, problems
