"""Prices from Yahoo Finance (free, no key). Futures on Yahoo are delayed
about 10 minutes, which is fine for context and bias but not for entries."""

import logging
import warnings
from datetime import datetime, timedelta, timezone

import pandas as pd

# yfinance prints a lot of noise when a symbol hiccups; the app reports
# problems in its own words instead.
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
warnings.filterwarnings("ignore", module=r"yfinance(\.|$)")

LABELS = {
    "gold": "Gold",
    "us30": "US30",
    "us100": "US100",
    "dollar": "Dollar index",
    "treasury_10y": "10Y T-note",
    "vix": "VIX",
}


def fetch_series(symbol: str) -> pd.Series:
    """5-minute closes for the last week, indexed in UTC."""
    import yfinance as yf  # imported here so demo mode works without it

    # yfinance switches its own warnings back on when imported; hide them again.
    warnings.filterwarnings("ignore", module=r"yfinance")

    df = yf.Ticker(symbol).history(period="7d", interval="5m", auto_adjust=False)
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


def snapshot(series: pd.Series, now: datetime) -> dict:
    last_time = series.index[-1].to_pydatetime()
    last = float(series.iloc[-1])

    def ago(minutes: int) -> float | None:
        t = pd.Timestamp(last_time - timedelta(minutes=minutes))
        sub = series.loc[:t]
        return float(sub.iloc[-1]) if not sub.empty else None

    week = series.loc[pd.Timestamp(last_time - timedelta(days=5)):]
    avg_5d = float(week.mean()) if len(week) > 50 else None

    return {
        "last": last,
        "last_time": last_time,
        "vs_5d": pct(avg_5d, last),
        "stale_min": int((now - last_time).total_seconds() // 60),
        "chg_30m": pct(ago(30), last),
        "chg_4h": pct(ago(240), last),
        "chg_24h": pct(ago(1440), last),
    }


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
