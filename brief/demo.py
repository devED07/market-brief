"""Made-up data for previewing the dashboard (run: main.py --demo).
Everything here is fake and clearly labelled as such on the page."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

NY = ZoneInfo("America/New_York")


# Made-up actual numbers and gasoline trend, standing in for FRED.
ACTUALS = {
    "JOLTS Job Openings": "7.19M",
    "ADP Non-Farm Employment Change": "58K",
}
GASOLINE = {"key": "cpi", "name": "Gasoline prices", "weight": 0.4, "hawk": 0.9,
            "text": "+2.7% vs the month before"}


def _demo_now() -> datetime:
    """A Thursday, 7:52am New York (8:52pm Manila), with CPI 38 minutes away."""
    real = datetime.now(NY)
    days_back = (real.weekday() - 3) % 7 or 7
    thu = (real - timedelta(days=days_back)).replace(hour=7, minute=52, second=0, microsecond=0)
    return thu.astimezone(timezone.utc)


def _ny(base_utc: datetime, day_offset: int, hh: int, mm: int) -> datetime:
    d = base_utc.astimezone(NY) + timedelta(days=day_offset)
    return d.replace(hour=hh, minute=mm, second=0, microsecond=0).astimezone(timezone.utc)


def _open(ts: pd.Timestamp) -> bool:
    ny = ts.tz_convert(NY)
    wd, h = ny.weekday(), ny.hour
    if wd == 5 or (wd == 4 and h >= 17) or (wd == 6 and h < 18):
        return False
    return h != 17


def build():
    now = _demo_now()
    # Calendar rows in the same shape as the Forex Factory feed
    def row(day, hh, mm, title, impact, fc, prev):
        t = _ny(now, day, hh, mm).astimezone(NY)
        return {"title": title, "country": "USD", "date": t.isoformat(), "impact": impact,
                "forecast": fc, "previous": prev}

    rows = [
        row(-3, 10, 0, "ISM Manufacturing PMI", "High", "49.6", "49.1"),
        row(-3, 10, 0, "ISM Manufacturing Prices", "Low", "58.5", "58.0"),
        row(-2, 8, 30, "Import Prices m/m", "Low", "0.1%", "0.3%"),
        row(-2, 10, 0, "JOLTS Job Openings", "High", "7.21M", "7.23M"),
        row(-1, 8, 15, "ADP Non-Farm Employment Change", "High", "42K", "31K"),
        row(-1, 10, 0, "ISM Services PMI", "High", "51.8", "52.0"),
        row(0, 7, 30, "Challenger Job Cuts y/y", "Low", "", "-12.4%"),
        row(0, 8, 30, "Core CPI m/m", "High", "0.3%", "0.3%"),
        row(0, 8, 30, "CPI m/m", "High", "0.3%", "0.4%"),
        row(0, 8, 30, "CPI y/y", "High", "2.9%", "3.0%"),
        row(0, 8, 30, "Unemployment Claims", "Medium", "221K", "218K"),
        row(1, 8, 30, "Non-Farm Employment Change", "High", "64K", "22K"),
        row(1, 8, 30, "Unemployment Rate", "High", "4.4%", "4.4%"),
        row(1, 8, 30, "Average Hourly Earnings m/m", "High", "0.3%", "0.3%"),
        row(1, 10, 0, "Prelim UoM Consumer Sentiment", "Medium", "53.4", "53.6"),
    ]

    # Reactions baked into the fake prices: (time, minutes, {key: % move})
    reactions = [
        (_ny(now, -3, 10, 0), 15, {"treasury_10y": +0.18, "dollar": -0.22, "gold": +0.55, "us30": +0.20, "us100": +0.30}),
        (_ny(now, -2, 10, 0), 15, {"treasury_10y": -0.02, "dollar": +0.03, "gold": -0.05, "us30": +0.02}),
        (_ny(now, -2, 8, 30), 15, {"treasury_10y": -0.08, "dollar": +0.12, "gold": -0.20, "us30": -0.05}),
        (_ny(now, -1, 8, 15), 15, {"treasury_10y": -0.15, "dollar": +0.24, "gold": -0.40, "us30": -0.15}),
        (_ny(now, -1, 10, 0), 15, {"treasury_10y": -0.30, "dollar": +0.42, "gold": -0.90, "us30": -0.45, "us100": -0.70}),
    ]
    targets = {"gold": 4282.4, "us30": 47655.0, "us100": 25480.0, "dollar": 100.21, "treasury_10y": 111.92, "vix": 17.84}
    noise = {"gold": 0.0004, "us30": 0.0003, "us100": 0.0004, "dollar": 0.00008, "treasury_10y": 0.00005, "vix": 0.002}
    drift_24h = {"gold": -0.0010, "us30": -0.0015, "us100": -0.0022, "dollar": +0.0005, "treasury_10y": -0.0004, "vix": +0.06}

    idx = pd.date_range(now - timedelta(days=7), now, freq="5min", tz="UTC")
    idx = idx[[_open(t) for t in idx]]
    rng = np.random.default_rng(7)
    series = {}
    tsec = np.array([t.timestamp() for t in idx])
    for key, target in targets.items():
        logp = np.cumsum(rng.normal(0, noise[key], len(idx)))
        for t, win, moves in reactions:
            m = moves.get(key)
            if not m:
                continue
            t0, t1 = t.timestamp(), (t + timedelta(minutes=win)).timestamp()
            ramp = np.clip((tsec - t0 + 300) / (t1 - t0), 0, 1)
            logp += ramp * np.log1p(m / 100)
        d0 = (now - timedelta(hours=24)).timestamp()
        logp += np.clip((tsec - d0) / (24 * 3600), 0, 1) * np.log1p(drift_24h[key])
        vals = np.exp(logp - logp[-1]) * target
        series[key] = pd.Series(vals, index=idx)

    hl_raw = [
        (25, "Gold slips as Treasury yields climb ahead of CPI", ["hawkish"]),
        (48, "Fed's official says no rush to cut rates with inflation sticky", ["hawkish"]),
        (95, "Dollar gains for a third day as traders trim rate-cut bets", ["hawkish"]),
        (140, "Stocks slide as investors brace for inflation data", ["risk-off"]),
        (210, "Oil steadies; Middle East tensions ease after talks", ["risk-on"]),
        (260, "New tariff threat rattles Asian markets", ["risk-off"]),
        (330, "Central bank gold buying stays strong, survey shows", []),
        (400, "Analysts split on whether CPI will cool further", []),
        (470, "Dow futures edge lower; earnings season winds down", []),
        (560, "Missile strike reported near border, safe-haven demand picks up", ["risk-off"]),
    ]
    headlines = [{"title": t, "source": "Sample source", "link": "#", "time": now - timedelta(minutes=m), "tags": tags}
                 for m, t, tags in hl_raw]
    return now, rows, series, headlines
