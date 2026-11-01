"""Geopolitical tension from the GDELT Project (free, open, no key).

GDELT monitors news worldwide every 15 minutes. We ask what share of all
coverage is about war, military action, missiles, terrorism and the like
(similar keywords to the academic Geopolitical Risk index), then compare the
last 24 hours with the normal level over the past 30 days.

More conflict coverage than usual = rising geopolitical risk, which tends to
support gold as a safe haven and weigh on stocks.
"""

import json
import statistics
import time
from datetime import datetime, timedelta, timezone

import requests

from .config import DATA_DIR

API = "https://api.gdeltproject.org/api/v2/doc/doc"
QUERY = ('(war OR military OR missile OR airstrike OR troops OR invasion OR '
         'terrorist OR "nuclear threat" OR escalation) sourcelang:english')
HEADERS = {"User-Agent": "Mozilla/5.0 (personal market brief app)"}
CACHE_FILE = DATA_DIR / "geo_cache.json"
CACHE_MAX_AGE_H = 6

LEVELS = [  # (ratio at or above, label)
    (1.4, "high"),
    (1.15, "elevated"),
    (0.85, "normal"),
    (0.0, "quieter than usual"),
]


def _parse_date(text: str) -> datetime | None:
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
    return None


def _download() -> list[tuple[datetime, float]]:
    # GDELT allows one request every 5 seconds per IP address. GitHub's
    # machines share IP addresses with other users, so wait and retry.
    for wait in (0, 6, 10, 15):
        time.sleep(wait)
        resp = requests.get(API, params={"query": QUERY, "mode": "timelinevol", "format": "json",
                                         "timespan": "30d"}, headers=HEADERS, timeout=30)
        if resp.status_code != 429:
            break
    resp.raise_for_status()
    try:
        data = resp.json()
    except ValueError:
        raise ValueError(f"not JSON: {resp.text[:160].strip()}") from None
    points = []
    for series in data.get("timeline", []):
        for p in series.get("data", []):
            when = _parse_date(p.get("date", ""))
            if when is not None and p.get("value") is not None:
                points.append((when, float(p["value"])))
    if not points:
        raise ValueError("GDELT returned no timeline")
    return sorted(points)


def summarize(points: list[tuple[datetime, float]], now: datetime) -> dict:
    recent = [v for t, v in points if now - t <= timedelta(hours=24)]
    by_day: dict = {}
    for t, v in points:
        if now - t > timedelta(hours=24):
            by_day.setdefault(t.date(), []).append(v)
    daily = [statistics.mean(vs) for vs in by_day.values()]
    if not recent or len(daily) < 7:
        raise ValueError("not enough GDELT history")
    base = statistics.median(daily)
    ratio = statistics.mean(recent) / base if base > 0 else 1.0
    level = next(label for cut, label in LEVELS if ratio >= cut)
    return {"ratio": ratio, "level": level, "time": now.isoformat()}


def fetch(now: datetime) -> tuple[dict | None, str]:
    """Returns (summary or None, problem text)."""
    try:
        summary = summarize(_download(), now)
        CACHE_FILE.write_text(json.dumps(summary), encoding="utf-8")
        return summary, ""
    except Exception as exc:
        detail = exc.__class__.__name__
        if isinstance(exc, ValueError):
            detail += f": {str(exc)[:200]}"
        resp = getattr(exc, "response", None)
        if resp is not None:
            detail += f" {resp.status_code}" + (", busy" if resp.status_code == 429 else f": {resp.text[:120].strip()}")
        problem = f"GDELT didn't respond ({detail})"
        try:
            cached = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            if now - datetime.fromisoformat(cached["time"]) < timedelta(hours=CACHE_MAX_AGE_H):
                return cached, ""
        except Exception:
            pass
        return None, problem


def score(summary: dict | None) -> tuple[float | None, str]:
    """+ = more geopolitical risk than normal. Roughly -0.75 to +1.5."""
    if not summary:
        return None, "No geopolitical data this time"
    r = summary["ratio"]
    s = max(-0.75, min(1.5, (r - 1.0) / 0.4))
    return s, f"Conflict news at {r:.1f}x its 30-day normal ({summary['level']})"
