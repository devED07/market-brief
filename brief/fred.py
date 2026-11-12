"""Actual numbers from FRED, the free data service of the St. Louis Fed.

The calendar feed has the forecast but not the number that came out. FRED
has the official figures, usually within an hour of the release. With them
the app can say "ADP came in at 42K against a 31K forecast" instead of only
reading how the market reacted.

Needs a free API key (see the README). Without one, nothing here runs and
the app reads every release from the market's reaction, as before.
"""

import json
import os
import re
from datetime import datetime, timedelta, timezone

import requests

from .config import DATA_DIR

API = "https://api.stlouisfed.org/fred"
ACTUALS_FILE = DATA_DIR / "actuals.json"
KEEP_DAYS = 45       # same as the lead-up log
RESOLVE_DAYS = 6     # how long to keep looking for a number FRED hasn't posted

# Calendar title (lower case) -> FRED series, how to turn it into the headline
# number, a scale to match the calendar's units, the size of a normal surprise,
# and the sign: +1 if a higher number is the hot / strong side, -1 if lower is.
SERIES = {
    "cpi m/m":                        ("CPIAUCSL", "pct_mom", 1, 0.1, 1),
    "core cpi m/m":                   ("CPILFESL", "pct_mom", 1, 0.1, 1),
    "cpi y/y":                        ("CPIAUCNS", "pct_yoy", 1, 0.1, 1),
    "core pce price index m/m":       ("PCEPILFE", "pct_mom", 1, 0.1, 1),
    "ppi m/m":                        ("PPIFIS", "pct_mom", 1, 0.2, 1),
    "core ppi m/m":                   ("PPIFES", "pct_mom", 1, 0.2, 1),
    "average hourly earnings m/m":    ("CES0500000003", "pct_mom", 1, 0.1, 1),
    "non-farm employment change":     ("PAYEMS", "diff", 1, 60, 1),
    "adp non-farm employment change": ("ADPMNUSNERSA", "diff", 0.001, 50, 1),
    "unemployment rate":              ("UNRATE", "level", 1, 0.1, -1),
    "unemployment claims":            ("ICSA", "level", 0.001, 12, -1),
    "jolts job openings":             ("JTSJOL", "level", 0.001, 0.3, 1),
    "retail sales m/m":               ("RSAFS", "pct_mom", 1, 0.3, 1),
    "core retail sales m/m":          ("RSFSXMV", "pct_mom", 1, 0.3, 1),
    "advance gdp q/q":                ("A191RL1Q225SBEA", "level", 1, 0.4, 1),
    "prelim gdp q/q":                 ("A191RL1Q225SBEA", "level", 1, 0.4, 1),
    "final gdp q/q":                  ("A191RL1Q225SBEA", "level", 1, 0.4, 1),
}

GASOLINE = "GASREGW"   # US regular gasoline, weekly average price
GAS_BIG = 3.0          # % change over a month that counts as a full point


def api_key(settings) -> str:
    return os.environ.get("FRED_API_KEY", "").strip() or getattr(settings, "fred_key", "")


def parse_num(text: str) -> float | None:
    """'0.3%' -> 0.3, '150K' -> 150.0, '' -> None"""
    t = str(text or "").strip().replace(",", "").lstrip("<>").rstrip("%KMBT").strip()
    try:
        return float(t)
    except ValueError:
        return None


def fmt_like(value: float, template: str) -> str:
    """Writes a number the way the calendar writes it (decimals and K / M / %)."""
    m = re.match(r"^[<>]?-?[\d,]*\.?(\d*)\s*([%KMBT]?)$", (template or "").strip())
    decimals = len(m.group(1)) if m else 1
    return f"{value:.{decimals}f}{m.group(2) if m else ''}"


def surprise(actual: str, forecast: str, sigma: float, sign: int) -> float | None:
    """How far the number landed from forecast, in "normal surprises".
    Positive = hot or strong (hawkish), the same direction as the reaction score."""
    a, f = parse_num(actual), parse_num(forecast)
    if a is None or f is None:
        return None
    return max(-2.0, min(2.0, round((a - f) / sigma, 6))) * sign


class _Fred:
    def __init__(self, key: str):
        self.key, self._obs, self._updated = key, {}, {}

    def _get(self, path: str, **params) -> dict:
        params.update(api_key=self.key, file_type="json")
        resp = requests.get(f"{API}/{path}", params=params, timeout=20)
        resp.raise_for_status()
        return resp.json()

    def observations(self, series: str) -> list[tuple]:
        """The latest 40 values, oldest first, as (date, value)."""
        if series not in self._obs:
            rows = self._get("series/observations", series_id=series, sort_order="desc", limit=40)
            out = []
            for o in rows.get("observations", []):
                try:
                    out.append((datetime.strptime(o["date"], "%Y-%m-%d").date(), float(o["value"])))
                except (KeyError, ValueError):
                    continue  # FRED writes "." for a missing value
            self._obs[series] = out[::-1]
        return self._obs[series]

    def last_updated(self, series: str) -> datetime:
        if series not in self._updated:
            text = self._get("series", series_id=series)["seriess"][0]["last_updated"]
            self._updated[series] = datetime.strptime(text + "00", "%Y-%m-%d %H:%M:%S%z")
        return self._updated[series]


def _headline_number(obs: list[tuple], calc: str) -> float | None:
    if not obs:
        return None
    d1, v1 = obs[-1]
    if calc == "level":
        return v1
    if calc in ("pct_mom", "diff"):
        if len(obs) < 2 or (d1 - obs[-2][0]).days > 35:  # a month is missing: don't guess
            return None
        v0 = obs[-2][1]
        return (v1 / v0 - 1) * 100 if calc == "pct_mom" else v1 - v0
    if calc == "pct_yoy":
        for d0, v0 in obs:
            if d0.year == d1.year - 1 and d0.month == d1.month:
                return (v1 / v0 - 1) * 100
    return None


def _load() -> dict:
    try:
        return json.loads(ACTUALS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def attach(releases: list[dict], now: datetime, key: str, persist: bool = True,
           fixed: dict | None = None) -> str:
    """Adds the actual number and its surprise to every event FRED covers,
    and a per-title summary to each release (rel["data"]). Returns a short
    problem note, or "". `fixed` supplies made-up actuals for demo mode."""
    store = _load() if persist else {}
    fred = _Fred(key) if key else None
    problem = ""

    for rel in releases:
        rel["data"] = {}
        if rel["time"] > now or rel.get("all_day"):
            continue
        for ev in rel["events"]:
            spec = SERIES.get(ev["title"].lower())
            if not spec:
                continue
            series, calc, scale, sigma, sign = spec
            eid = f"{rel['time'].isoformat()}|{ev['title']}"
            actual = (fixed or {}).get(ev["title"]) or store.get(eid, {}).get("actual")
            if not actual and fred and not problem and now - rel["time"] < timedelta(days=RESOLVE_DAYS):
                try:
                    if fred.last_updated(series) >= rel["time"] - timedelta(hours=1):
                        value = _headline_number(fred.observations(series), calc)
                        if value is not None:
                            actual = fmt_like(value * scale, ev["forecast"] or ev["previous"])
                except requests.HTTPError as exc:
                    code = exc.response.status_code if exc.response is not None else 0
                    problem = ("FRED rejected the API key" if code in (400, 401, 403)
                               else f"FRED didn't respond (HTTP {code})")
                except Exception as exc:
                    problem = f"FRED didn't respond ({exc.__class__.__name__})"
            if not actual:
                continue
            z = surprise(actual, ev["forecast"], sigma, sign)
            a, f = parse_num(actual), parse_num(ev["forecast"])
            if a is not None and f is not None and abs(a - f) / sigma > 8:
                continue  # wildly off: the units don't match, so don't trust it
            store[eid] = {"actual": actual, "time": rel["time"].isoformat()}
            ev["actual"], ev["surprise"] = actual, z
            if z is not None:
                rel["data"][ev["title"]] = {"z": z, "text": f"{actual} vs {ev['forecast']} forecast"}

    if persist:
        cutoff = (now - timedelta(days=KEEP_DAYS)).isoformat()
        store = {k: v for k, v in store.items() if v.get("time", "") >= cutoff}
        ACTUALS_FILE.write_text(json.dumps(store), encoding="utf-8")
    return problem


def gasoline_lead(now: datetime, key: str) -> dict | None:
    """Pump prices over the last four weeks against the four before. Gasoline
    drives a lot of the month-to-month swing in headline CPI."""
    if not key:
        return None
    try:
        obs = _Fred(key).observations(GASOLINE)
    except Exception:
        return None
    if len(obs) < 8 or (now.date() - obs[-1][0]).days > 21:
        return None
    recent = sum(v for _, v in obs[-4:]) / 4
    before = sum(v for _, v in obs[-8:-4]) / 4
    change = (recent / before - 1) * 100
    last = obs[-1][0]
    return {
        "key": "cpi", "name": "Gasoline prices", "weight": 0.4,
        "hawk": max(-2.0, min(2.0, change / GAS_BIG)),
        "text": f"{change:+.1f}% vs the month before",
        "time": datetime(last.year, last.month, last.day, tzinfo=timezone.utc),
    }
