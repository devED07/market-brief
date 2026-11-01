"""US economic calendar from the free Forex Factory weekly feed.

The feed has each release's time, impact, forecast and previous value.
It does not carry the actual number, so the bias engine reads the
surprise from how the market reacted instead (see bias.py).
"""

import json
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests

from .config import DATA_DIR

FEEDS = [
    "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
    "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
]
CACHE_FILE = DATA_DIR / "calendar_cache.json"
CACHE_MAX_AGE_MIN = 60  # the feed asks people not to hammer it
NEW_YORK = ZoneInfo("America/New_York")

# Releases that move gold and the Dow the most. Matched against the title.
TOP_TIER = (
    "non-farm", "cpi", "federal funds", "fomc", "pce", "average hourly earnings",
    "unemployment rate", "advance gdp", "retail sales", "ppi", "ism manufacturing",
    "ism services", "powell", "jolts",
)

# Events with no fixed release time. The feed still gives them a clock time,
# so the app lists them but doesn't count down to them or score them.
ALL_DAY_WORDS = ("election", "referendum")

HEADERS = {"User-Agent": "Mozilla/5.0 (personal market brief app)"}


def _parse_time(text: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=NEW_YORK)
    return dt.astimezone(timezone.utc)


def _priority(title: str) -> int:
    """Which title leads a group: NFP before earnings, CPI before claims..."""
    low = title.lower()
    return next((i for i, key in enumerate(TOP_TIER) if key in low), len(TOP_TIER))


def _weight(title: str, impact: str) -> float:
    base = {"High": 1.0, "Medium": 0.5}.get(impact, 0.0)
    low = title.lower()
    if base and "adp" not in low and any(key in low for key in TOP_TIER):
        base *= 1.5
    return base


def _download() -> list[dict]:
    rows: list[dict] = []
    for i, url in enumerate(FEEDS):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            resp.raise_for_status()
            rows.extend(resp.json())
        except Exception:
            if i == 0:  # this week's feed is the one that matters
                raise
    return rows


def load_raw() -> tuple[list[dict], bool, str]:
    """Returns (rows, is_fresh, note). Uses the cache when it's recent
    or when the feed can't be reached."""
    cached = None
    if CACHE_FILE.exists():
        try:
            cached = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            cached = None

    if cached and time.time() - cached.get("fetched_at", 0) < CACHE_MAX_AGE_MIN * 60:
        return cached["rows"], True, ""

    try:
        rows = _download()
        CACHE_FILE.write_text(json.dumps({"fetched_at": time.time(), "rows": rows}), encoding="utf-8")
        return rows, True, ""
    except Exception as exc:
        if cached:
            age_min = int((time.time() - cached.get("fetched_at", 0)) / 60)
            return cached["rows"], False, f"Calendar feed unreachable ({exc.__class__.__name__}); using a copy from {age_min} min ago."
        return [], False, f"Calendar feed unreachable ({exc.__class__.__name__}) and no saved copy yet."


def usd_events(rows: list[dict]) -> list[dict]:
    """High and medium impact USD events, oldest first."""
    seen = set()
    events = []
    for r in rows:
        if r.get("country") != "USD":
            continue
        impact = r.get("impact", "")
        title = (r.get("title") or "").strip()
        weight = _weight(title, impact)
        if weight <= 0:
            continue
        when = _parse_time(r.get("date", ""))
        if when is None:
            continue
        key = (title, when)
        if key in seen:
            continue
        seen.add(key)
        events.append({
            "title": title,
            "time": when,
            "impact": impact,
            "forecast": (r.get("forecast") or "").strip(),
            "previous": (r.get("previous") or "").strip(),
            "weight": weight,
        })
    events.sort(key=lambda e: e["time"])
    return events


def group_releases(events: list[dict]) -> list[dict]:
    """Events at the same minute (CPI m/m, core CPI, CPI y/y...) are one
    market moment, so they're scored once."""
    groups: dict[datetime, list[dict]] = {}
    for e in events:
        groups.setdefault(e["time"], []).append(e)

    releases = []
    for when, items in sorted(groups.items()):
        items.sort(key=lambda e: (-e["weight"], _priority(e["title"])))
        titles = [e["title"] for e in items]
        joined = " ".join(titles).lower()
        all_day = any(k in joined for k in ALL_DAY_WORDS)
        if "press conference" in joined:
            window = 45
        elif "fomc" in joined or "federal funds" in joined:
            window = 30
        else:
            window = 15
        releases.append({
            "time": when,
            "events": items,
            "headline": titles[0],
            "others": titles[1:],
            "weight": max(e["weight"] for e in items),
            "impact": "High" if any(e["impact"] == "High" for e in items) else "Medium",
            "top_tier": any(e["weight"] >= 1.5 for e in items),
            "window_min": window,
            "all_day": all_day,
        })
    return releases
