"""Offline replay script for the live-market drivers in brief/bias.py.

Downloads 1-hour history from Yahoo Finance for Gold, US30, US100, DXY,
10Y T-notes, and VIX, replays the live drivers (dollar/yields, VIX risk
mood, gold sell-everything, equity flight-to-safety, and price trend), and
prints forward 4h and 24h hit rates and mean returns per bias bucket.

Usage:
    python scripts/backtest.py
    python scripts/backtest.py --period 60d --interval 1h
"""

import argparse
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from brief import bias as B
from brief.config import load_settings
from brief.prices import pct
from brief.util import NEW_YORK

ZERO_TONE = {
    "rates": 0.0,
    "risk": 0.0,
    "count": {"hawkish": 0, "dovish": 0, "risk-off": 0, "risk-on": 0, "geopolitics": 0, "de-escalation": 0},
}


def fetch_hourly(symbols: dict[str, str], period: str, interval: str) -> dict[str, pd.Series]:
    import yfinance as yf

    out: dict[str, pd.Series] = {}
    for key, sym in symbols.items():
        df = yf.Ticker(sym).history(period=period, interval=interval, auto_adjust=False)
        if df is None or df.empty or "Close" not in df:
            raise RuntimeError(f"No history returned for {key} ({sym})")
        s = df["Close"].dropna()
        s.index = pd.to_datetime(s.index, utc=True)
        out[key] = s.sort_index()
    return out


def snap_at(series: pd.Series, t: pd.Timestamp) -> dict | None:
    sub = series.loc[:t]
    if len(sub) < 12:
        return None
    last_time = sub.index[-1]
    last = float(sub.iloc[-1])

    def ago(hours: int, max_gap_h: int) -> float | None:
        target = last_time - pd.Timedelta(hours=hours)
        prior = sub.loc[:target]
        if prior.empty or (target - prior.index[-1]) > pd.Timedelta(hours=max_gap_h):
            return None
        return float(prior.iloc[-1])

    ny_dates = sub.index.tz_convert(NEW_YORK).normalize()
    last_5 = ny_dates.unique()[-5:]
    win = sub[ny_dates.isin(last_5)]
    avg_5d = float(win.mean()) if len(win) >= 12 else None

    return {
        "last": last,
        "last_time": last_time.to_pydatetime(),
        "vs_5d": pct(avg_5d, last),
        "stale_min": max(0, int((t - last_time).total_seconds() // 60)),
        "chg_30m": None,
        "chg_4h": pct(ago(4, max_gap_h=6), last),
        "chg_24h": pct(ago(24, max_gap_h=72), last),
    }


def forward_return(series: pd.Series, t: pd.Timestamp, hours: int) -> float | None:
    cur = series.loc[:t]
    if cur.empty:
        return None
    target = t + pd.Timedelta(hours=hours)
    fut = series.loc[target:]
    if fut.empty or (fut.index[0] - target) > pd.Timedelta(hours=6):
        return None
    return pct(float(cur.iloc[-1]), float(fut.iloc[0]))


def replay(series_map: dict[str, pd.Series]) -> dict[str, list[dict]]:
    gold_idx = series_map["gold"].index
    start = gold_idx[0] + pd.Timedelta(days=7)
    end = gold_idx[-1] - pd.Timedelta(hours=24)
    results: dict[str, list[dict]] = {"gold": [], "us30": [], "us100": []}

    for t in gold_idx:
        if t < start or t > end:
            continue
        snaps = {}
        for key, s in series_map.items():
            sn = snap_at(s, t)
            if sn is not None:
                snaps[key] = sn
        if not {"gold", "us30", "us100"}.issubset(snaps):
            continue
        now_dt = t.to_pydatetime()
        bias = B.build([], snaps, ZERO_TONE, now_dt)
        for key in ("gold", "us30", "us100"):
            r4 = forward_return(series_map[key], t, 4)
            r24 = forward_return(series_map[key], t, 24)
            if r4 is None and r24 is None:
                continue
            results[key].append({
                "score": bias[key]["score"],
                "label": bias[key]["label"],
                "r4": r4,
                "r24": r24,
            })
    return results


def summarize(key: str, rows: list[dict]) -> None:
    print(f"\n=== {key.upper()} ({len(rows)} hourly bars evaluated) ===")
    if not rows:
        print("  Not enough overlapping bars.")
        return
    buckets = [
        ("Bullish (>= +4.0)", lambda s: s >= 4.0, 1),
        ("Leaning bull (+1.5..+4)", lambda s: 1.5 <= s < 4.0, 1),
        ("Flat (-1.5..+1.5)", lambda s: -1.5 < s < 1.5, 0),
        ("Leaning bear (-4..-1.5)", lambda s: -4.0 < s <= -1.5, -1),
        ("Bearish (<= -4.0)", lambda s: s <= -4.0, -1),
    ]
    print(f"  {'Bucket':<25} {'N':>5} {'4h mean':>9} {'4h hit':>8} {'24h mean':>9} {'24h hit':>8}")
    for name, pred, sign in buckets:
        sub = [r for r in rows if pred(r["score"])]
        if not sub:
            print(f"  {name:<25} {0:>5} {'--':>9} {'--':>8} {'--':>9} {'--':>8}")
            continue
        r4s = [r["r4"] for r in sub if r["r4"] is not None]
        r24s = [r["r24"] for r in sub if r["r24"] is not None]
        m4 = f"{sum(r4s)/len(r4s):+.3f}%" if r4s else "--"
        m24 = f"{sum(r24s)/len(r24s):+.3f}%" if r24s else "--"
        if sign != 0:
            h4 = f"{sum(1 for x in r4s if x * sign > 0)/len(r4s)*100:.0f}%" if r4s else "--"
            h24 = f"{sum(1 for x in r24s if x * sign > 0)/len(r24s)*100:.0f}%" if r24s else "--"
        else:
            h4 = h24 = "--"
        print(f"  {name:<25} {len(sub):>5} {m4:>9} {h4:>8} {m24:>9} {h24:>8}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Replay live bias drivers on historical Yahoo Finance bars")
    ap.add_argument("--period", default="60d", help="yfinance lookback period (default: 60d)")
    ap.add_argument("--interval", default="1h", help="bar interval (default: 1h)")
    args = ap.parse_args()

    settings = load_settings()
    symbols = {
        "gold": settings.gold,
        "us30": settings.us30,
        "us100": settings.us100,
        "dollar": settings.dollar,
        "treasury_10y": settings.treasury_10y,
        "vix": settings.vix,
    }
    print(f"Downloading {args.period} of {args.interval} bars from Yahoo Finance...")
    series_map = fetch_hourly(symbols, args.period, args.interval)
    results = replay(series_map)
    for key in ("gold", "us30", "us100"):
        summarize(key, results[key])


if __name__ == "__main__":
    main()
