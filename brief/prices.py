"""Prices from Yahoo Finance (free, no key). Futures on Yahoo are delayed
about 10 minutes, which is fine for context and bias but not for entries."""

import json
import logging
import warnings
from datetime import datetime, timedelta, timezone

import pandas as pd

from .config import DATA_DIR
from .util import NEW_YORK, atomic_write_json

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


def daily_levels(series: pd.Series, days: int = 5) -> list[dict]:
    """Completed NY trading-day highs, lows, closes, and session levels (newest first)."""
    if series is None or series.empty:
        return []
    series = series.sort_index()
    ny_idx = series.index.tz_convert(NEW_YORK)
    ny_dates = ny_idx.normalize()
    uniq_dates = ny_dates.unique()
    if len(uniq_dates) < 2:
        return []
    completed = list(uniq_dates[-(days + 1):-1])[::-1]

    def _hl(sub: pd.Series) -> tuple[float | None, float | None]:
        if sub.empty:
            return None, None
        return float(sub.max()), float(sub.min())

    out: list[dict] = []
    for d in completed:
        mask = ny_dates == d
        day_s = series[mask]
        if day_s.empty:
            continue
        day_ny = ny_idx[mask]
        hi = float(day_s.max())
        lo = float(day_s.min())
        op = float(day_s.iloc[0])
        cl = float(day_s.iloc[-1])
        hours = day_ny.hour
        asia_h, asia_l = _hl(day_s[(hours >= 0) & (hours < 3)])
        lon_h, lon_l = _hl(day_s[(hours >= 3) & (hours < 8)])
        ny_h, ny_l = _hl(day_s[(hours >= 8) & (hours < 17)])
        out.append({
            "date": d.strftime("%Y-%m-%d"),
            "label": d.strftime("%a, %b %d").replace(" 0", " "),
            "high": hi,
            "low": lo,
            "close": cl,
            "chg_pct": pct(op, cl),
            "range_pct": round((hi - lo) / op * 100.0, 2) if op > 0 else None,
            "asia_h": asia_h,
            "asia_l": asia_l,
            "london_h": lon_h,
            "london_l": lon_l,
            "ny_h": ny_h,
            "ny_l": ny_l,
        })
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

    ny_dates = series.index.tz_convert(NEW_YORK).normalize()
    uniq_dates = ny_dates.unique()
    last_5 = uniq_dates[-5:]
    window = series[ny_dates.isin(last_5)]
    avg_5d = float(window.mean()) if len(window) > 50 else None

    pdh = pdl = range_used = None
    if len(uniq_dates) >= 2:
        prev_day = series[ny_dates == uniq_dates[-2]]
        if not prev_day.empty:
            pdh = float(prev_day.max())
            pdl = float(prev_day.min())
        today_bars = series[ny_dates == uniq_dates[-1]]
        prior_ranges = []
        for d in uniq_dates[-6:-1]:
            day_s = series[ny_dates == d]
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
