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
from .util import atomic_write_json, make_session

API = "https://api.stlouisfed.org/fred"
ACTUALS_FILE = DATA_DIR / "actuals.json"
KEEP_DAYS = 45       # same as the lead-up log
RESOLVE_DAYS = 6     # how long to keep looking for a number FRED hasn't posted

# Calendar title (lower case) -> FRED series, how to turn it into the headline
# number, a scale to match the calendar's units, the size of a normal surprise,
# sign (+1 if higher is hot/strong, -1 if lower is), and canonical unit.
SERIES = {
    "cpi m/m":                        ("CPIAUCSL", "pct_mom", 1, 0.1, 1, "%"),
    "core cpi m/m":                   ("CPILFESL", "pct_mom", 1, 0.1, 1, "%"),
    "cpi y/y":                        ("CPIAUCNS", "pct_yoy", 1, 0.1, 1, "%"),
    "core pce price index m/m":       ("PCEPILFE", "pct_mom", 1, 0.1, 1, "%"),
    "ppi m/m":                        ("PPIFIS", "pct_mom", 1, 0.2, 1, "%"),
    "core ppi m/m":                   ("PPIFES", "pct_mom", 1, 0.2, 1, "%"),
    "average hourly earnings m/m":    ("CES0500000003", "pct_mom", 1, 0.1, 1, "%"),
    "non-farm employment change":     ("PAYEMS", "diff", 1, 60, 1, "K"),
    "adp non-farm employment change": ("ADPMNUSNERSA", "diff", 0.001, 50, 1, "K"),
    "unemployment rate":              ("UNRATE", "level", 1, 0.1, -1, "%"),
    "unemployment claims":            ("ICSA", "level", 0.001, 12, -1, "K"),
    "jolts job openings":             ("JTSJOL", "level", 0.001, 0.3, 1, "M"),
    "retail sales m/m":               ("RSAFS", "pct_mom", 1, 0.3, 1, "%"),
    "core retail sales m/m":          ("RSFSXMV", "pct_mom", 1, 0.3, 1, "%"),
    "advance gdp q/q":                ("A191RL1Q225SBEA", "level", 1, 0.4, 1, "%"),
    "prelim gdp q/q":                 ("A191RL1Q225SBEA", "level", 1, 0.4, 1, "%"),
    "final gdp q/q":                  ("A191RL1Q225SBEA", "level", 1, 0.4, 1, "%"),
}

UNIT_MULT = {"": 1.0, "%": 1.0, "K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}
SCALE_UNITS = ("K", "M", "B", "T")

GASOLINE = "GASREGW"   # US regular gasoline, weekly average price
GAS_BIG = 3.0          # % change over a month that counts as a full point


def _series_freq(series: str) -> str:
    if series == "ICSA":
        return "weekly"
    if series == "A191RL1Q225SBEA":
        return "quarterly"
    if series == "JTSJOL":
        return "monthly_lag2"
    return "monthly"


def api_key(settings) -> str:
    return os.environ.get("FRED_API_KEY", "").strip() or getattr(settings, "fred_key", "")


def parse_num_unit(text: str) -> tuple[float | None, str]:
    """'0.3%' -> (0.3, '%'), '1.05M' -> (1.05, 'M'), '' -> (None, '')."""
    t = str(text or "").strip().replace(",", "").lstrip("<>").strip()
    unit = ""
    if t and t[-1].upper() in UNIT_MULT and t[-1] != "":
        if t[-1].upper() in ("%", "K", "M", "B", "T"):
            unit = t[-1].upper()
            t = t[:-1].strip()
    try:
        return float(t), unit
    except ValueError:
        return None, ""


def parse_num(text: str) -> float | None:
    """'0.3%' -> 0.3, '150K' -> 150.0, '' -> None"""
    return parse_num_unit(text)[0]


def _convert_units(val: float, from_unit: str, to_unit: str) -> float:
    if from_unit in SCALE_UNITS and to_unit in SCALE_UNITS and from_unit != to_unit:
        return val * (UNIT_MULT[from_unit] / UNIT_MULT[to_unit])
    return val


def fmt_like(value: float, template: str, default_unit: str = "") -> str:
    """Writes a number the way the calendar writes it (decimals and K / M / %)."""
    text = (template or "").strip()
    m = re.match(r"^[<>]?-?[\d,]*\.?(\d*)\s*([%KMBT]?)$", text, re.I)
    decimals = len(m.group(1)) if m else 1
    t_unit = m.group(2).upper() if m and m.group(2) else ""
    if t_unit and default_unit:
        value = _convert_units(value, default_unit, t_unit)
    out_unit = t_unit or default_unit
    return f"{value:.{decimals}f}{out_unit}"


def surprise(actual: str, forecast: str, sigma: float, sign: int, unit: str = "") -> float | None:
    """How far the number landed from forecast, in "normal surprises".
    Positive = hot or strong (hawkish), the same direction as the reaction score."""
    if not sigma:
        return None
    a, ua = parse_num_unit(actual)
    f, uf = parse_num_unit(forecast)
    if a is None or f is None:
        return None
    if unit in SCALE_UNITS:
        a = _convert_units(a, ua or unit, unit)
        f = _convert_units(f, uf or unit, unit)
    elif not unit and ua in SCALE_UNITS and uf in SCALE_UNITS and ua != uf:
        a = _convert_units(a, ua, uf)
    return max(-2.0, min(2.0, round((a - f) / sigma, 6))) * sign


def _parse_fred_ts(text: str) -> datetime:
    """Parse FRED timestamp strings such as '2026-11-27 08:30:00-06' or ISO formats."""
    t = (text or "").strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    m = re.match(r"^(.*\d)([+-]\d{2})(?::?(\d{2}))?$", t)
    if m:
        t = f"{m.group(1)}{m.group(2)}:{m.group(3) or '00'}"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class _Fred:
    def __init__(self, key: str, session: requests.Session | None = None):
        self.key = key
        self._obs: dict[str, list[tuple]] = {}
        self._updated: dict[str, datetime] = {}
        self._session = session or make_session()

    def _get(self, path: str, **params) -> dict:
        params.update(api_key=self.key, file_type="json")
        resp = self._session.get(f"{API}/{path}", params=params, timeout=20)
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
            self._updated[series] = _parse_fred_ts(text)
        return self._updated[series]


def _headline_number(obs: list[tuple], calc: str, rel_time: datetime | None = None,
                     freq: str = "monthly") -> float | None:
    if not obs:
        return None
    if rel_time is not None:
        rel_date = rel_time.date()
        if freq in ("monthly", "monthly_lag2"):
            cutoff = rel_date.replace(day=1)
            eligible = [(d, v) for d, v in obs if d < cutoff]
        else:
            eligible = [(d, v) for d, v in obs if d <= rel_date]
        if not eligible:
            return None
        d1, v1 = eligible[-1]
        age = (rel_date - d1).days
        bounds = {
            "weekly": (0, 16),
            "monthly": (1, 65),
            "monthly_lag2": (1, 95),
            "quarterly": (15, 195),
        }
        lo, hi = bounds.get(freq, (0, 95))
        if not (lo <= age <= hi):
            return None
        obs = eligible
    else:
        d1, v1 = obs[-1]

    if calc == "level":
        return v1
    if calc in ("pct_mom", "diff"):
        if len(obs) < 2 or (d1 - obs[-2][0]).days > 35:  # a month is missing: don't guess
            return None
        v0 = obs[-2][1]
        if calc == "pct_mom":
            return (v1 / v0 - 1) * 100 if v0 != 0 else None
        return v1 - v0
    if calc == "pct_yoy":
        for d0, v0 in obs:
            if d0.year == d1.year - 1 and d0.month == d1.month:
                return (v1 / v0 - 1) * 100 if v0 != 0 else None
    return None


def _load() -> dict:
    try:
        return json.loads(ACTUALS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _is_auth_error(exc: requests.HTTPError) -> bool:
    resp = exc.response
    if resp is None:
        return False
    if resp.status_code in (401, 403):
        return True
    if resp.status_code == 400:
        try:
            msg = str(resp.json().get("error_message", "")).lower()
        except Exception:
            msg = resp.text.lower()
        return "api_key" in msg or "api key" in msg
    return False


def attach(releases: list[dict], now: datetime, key: str, persist: bool = True,
           fixed: dict | None = None, fred: _Fred | None = None) -> str:
    """Adds the actual number and its surprise to every event FRED covers,
    and a per-title summary to each release (rel["data"]). Returns a short
    problem note, or "". `fixed` supplies made-up actuals for demo mode."""
    store = _load() if persist else {}
    client = fred or (_Fred(key) if key else None)
    auth_problem = ""
    series_problems: list[str] = []

    for rel in releases:
        rel["data"] = {}
        if rel["time"] > now or rel.get("all_day"):
            continue
        for ev in rel["events"]:
            spec = SERIES.get(ev["title"].lower())
            if not spec:
                continue
            series, calc, scale, sigma, sign, unit = spec
            eid = f"{rel['time'].isoformat()}|{ev['title']}"
            actual = (fixed or {}).get(ev["title"]) or store.get(eid, {}).get("actual")
            if not actual and client and not auth_problem and now - rel["time"] < timedelta(days=RESOLVE_DAYS):
                try:
                    if client.last_updated(series) >= rel["time"] - timedelta(hours=1):
                        value = _headline_number(
                            client.observations(series), calc,
                            rel_time=rel["time"], freq=_series_freq(series),
                        )
                        if value is not None:
                            actual = fmt_like(value * scale, ev["forecast"] or ev["previous"], default_unit=unit)
                except requests.HTTPError as exc:
                    if _is_auth_error(exc):
                        auth_problem = "FRED rejected the API key"
                    else:
                        code = exc.response.status_code if exc.response is not None else 0
                        note = f"FRED {series} error (HTTP {code})"
                        if note not in series_problems:
                            series_problems.append(note)
                except Exception as exc:
                    note = f"FRED didn't respond ({exc.__class__.__name__})"
                    if note not in series_problems:
                        series_problems.append(note)
            if not actual:
                continue
            z = surprise(actual, ev["forecast"], sigma, sign, unit=unit)
            a, ua = parse_num_unit(actual)
            f, uf = parse_num_unit(ev["forecast"])
            if a is not None and f is not None:
                if unit in SCALE_UNITS:
                    a_norm = _convert_units(a, ua or unit, unit)
                    f_norm = _convert_units(f, uf or unit, unit)
                else:
                    a_norm, f_norm = a, f
                if sigma and abs(a_norm - f_norm) / sigma > 8:
                    continue  # wildly off: the units don't match, so don't trust it
            store[eid] = {"actual": actual, "time": rel["time"].isoformat()}
            ev["actual"], ev["surprise"] = actual, z
            if z is not None:
                rel["data"][ev["title"]] = {"z": z, "text": f"{actual} vs {ev['forecast']} forecast"}

    if persist:
        cutoff = (now - timedelta(days=KEEP_DAYS)).isoformat()
        store = {k: v for k, v in store.items() if v.get("time", "") >= cutoff}
        atomic_write_json(ACTUALS_FILE, store)
    return auth_problem or ("; ".join(series_problems[:2]) if series_problems else "")


def gasoline_lead(now: datetime, key: str, fred: _Fred | None = None) -> dict | None:
    """Pump prices over the last four weeks against the four before. Gasoline
    drives a lot of the month-to-month swing in headline CPI."""
    if not key and fred is None:
        return None
    try:
        client = fred or _Fred(key)
        obs = client.observations(GASOLINE)
    except Exception:
        return None
    if len(obs) < 8 or (now.date() - obs[-1][0]).days > 21:
        return None
    recent = sum(v for _, v in obs[-4:]) / 4
    before = sum(v for _, v in obs[-8:-4]) / 4
    if before == 0:
        return None
    change = (recent / before - 1) * 100
    last = obs[-1][0]
    return {
        "key": "cpi", "name": "Gasoline prices", "weight": 0.4,
        "hawk": max(-2.0, min(2.0, change / GAS_BIG)),
        "text": f"{change:+.1f}% vs the month before",
        "time": datetime(last.year, last.month, last.day, tzinfo=timezone.utc),
    }
