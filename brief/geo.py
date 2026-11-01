"""Geopolitical tension from the GDELT Project's live event feed (free, open).

Every 15 minutes GDELT publishes a small file of world events it found in the
news, each coded by type (threats, military posturing, coercion, attacks,
fighting...) and by the countries involved. For events between two different
countries, we measure what share of news coverage is about conflict, then
compare the last 24 hours with the normal level over the past 30 days.

More conflict than usual = rising geopolitical risk, which tends to support
gold as a safe haven and weigh on stocks.

Each run only downloads the files published since the last run (about 50 KB
each). The first run samples the past 30 days to build a baseline.
"""

import csv
import io
import json
import statistics
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import requests

from .config import DATA_DIR

FEED = "http://data.gdeltproject.org/gdeltv2/{stamp}.export.CSV.zip"
LAST_UPDATE = "http://data.gdeltproject.org/gdeltv2/lastupdate.txt"
HEADERS = {"User-Agent": "Mozilla/5.0 (personal market brief app)"}
HISTORY_FILE = DATA_DIR / "geo_history.json"
CACHE_FILE = DATA_DIR / "geo_cache.json"

KEEP_DAYS = 31
BACKFILL_STEP_H = 3      # first run: one file every 3 hours over 30 days
MAX_NEW_FILES = 12       # per run, newest first
CONFLICT_ROOTS = {"13", "15", "17", "18", "19", "20"}  # threaten, military posture, coerce, assault, fight, mass violence

# GDELT 2.0 event columns we use
COL_ACTOR1_COUNTRY, COL_ACTOR2_COUNTRY, COL_ROOT, COL_ARTICLES = 7, 17, 28, 33

LEVELS = [  # (ratio at or above, label)
    (1.4, "high"),
    (1.15, "elevated"),
    (0.85, "normal"),
    (0.0, "quieter than usual"),
]


def _stamp(t: datetime) -> str:
    return t.strftime("%Y%m%d%H%M%S")


def _parse(stamp: str) -> datetime:
    return datetime.strptime(stamp, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def _slot(t: datetime) -> datetime:
    return t.replace(minute=t.minute - t.minute % 15, second=0, microsecond=0)


def _latest_slot() -> datetime:
    resp = requests.get(LAST_UPDATE, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    for part in resp.text.split():
        if part.endswith(".export.CSV.zip"):
            return _parse(part.rsplit("/", 1)[-1].split(".")[0])
    raise ValueError("couldn't read GDELT's latest update")


def count_events(raw: str) -> tuple[int, int]:
    """(conflict articles, all articles) for events between two countries."""
    conflict = total = 0
    for row in csv.reader(io.StringIO(raw), delimiter="\t"):
        if len(row) <= COL_ARTICLES:
            continue
        a, b = row[COL_ACTOR1_COUNTRY], row[COL_ACTOR2_COUNTRY]
        if not a or not b or a == b:
            continue
        try:
            n = int(row[COL_ARTICLES] or 1)
        except ValueError:
            n = 1
        total += n
        if row[COL_ROOT] in CONFLICT_ROOTS:
            conflict += n
    return conflict, total


def _download(slot: datetime) -> tuple[int, int] | None:
    resp = requests.get(FEED.format(stamp=_stamp(slot)), headers=HEADERS, timeout=30)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        raw = z.read(z.namelist()[0]).decode("utf-8", errors="replace")
    return count_events(raw)


def _load_history() -> dict[str, list[int]]:
    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def update_history(now: datetime) -> dict[str, list[int]]:
    hist = _load_history()
    cutoff = now - timedelta(days=KEEP_DAYS)
    hist = {k: v for k, v in hist.items() if _parse(k) >= cutoff}
    latest = _latest_slot()

    wanted = []
    # New files since the last run, newest first
    t = latest
    while len(wanted) < MAX_NEW_FILES and t > now - timedelta(hours=26):
        if _stamp(t) not in hist:
            wanted.append(t)
        elif wanted:
            break
        t -= timedelta(minutes=15)
    # First run (or a long gap): sample the past 30 days for a baseline
    if len({k[:8] for k in hist}) < 7:
        t = _slot(latest - timedelta(hours=BACKFILL_STEP_H))
        while t > now - timedelta(days=30):
            if _stamp(t) not in hist:
                wanted.append(t)
            t -= timedelta(hours=BACKFILL_STEP_H)

    def safe(slot):
        try:
            return slot, _download(slot)
        except Exception:
            return slot, None

    with ThreadPoolExecutor(max_workers=6) as pool:
        for slot, counts in pool.map(safe, wanted):
            if counts and counts[1] > 0:
                hist[_stamp(slot)] = list(counts)
    HISTORY_FILE.write_text(json.dumps(hist), encoding="utf-8")
    return hist


def summarize(hist: dict[str, list[int]], now: datetime) -> dict:
    recent_c = recent_t = 0
    days: dict[str, list[int]] = {}
    for stamp, (c, tot) in hist.items():
        if now - _parse(stamp) <= timedelta(hours=24):
            recent_c += c
            recent_t += tot
        else:
            d = days.setdefault(stamp[:8], [0, 0])
            d[0] += c
            d[1] += tot
    daily = [c / tot for c, tot in days.values() if tot > 0]
    if recent_t == 0 or len(daily) < 7:
        raise ValueError(f"not enough GDELT history yet ({len(daily)} days)")
    base = statistics.median(daily)
    share = recent_c / recent_t
    ratio = share / base if base > 0 else 1.0
    level = next(label for cut, label in LEVELS if ratio >= cut)
    return {"ratio": ratio, "level": level, "share": share, "time": now.isoformat()}


def fetch(now: datetime) -> tuple[dict | None, str]:
    """Returns (summary or None, problem text)."""
    try:
        summary = summarize(update_history(now), now)
        CACHE_FILE.write_text(json.dumps(summary), encoding="utf-8")
        return summary, ""
    except Exception as exc:
        problem = f"Geopolitical data unavailable ({exc.__class__.__name__}: {str(exc)[:120]})"
        try:
            cached = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            if now - datetime.fromisoformat(cached["time"]) < timedelta(hours=6):
                return cached, ""
        except Exception:
            pass
        return None, problem


def score(summary: dict | None) -> tuple[float | None, str]:
    """+ = more conflict between countries than normal. Roughly -0.75 to +1.5."""
    if not summary:
        return None, "No geopolitical data this time"
    r = summary["ratio"]
    s = max(-0.75, min(1.5, (r - 1.0) / 0.4))
    return s, f"Conflict between countries at {r:.1f}x its 30-day normal ({summary['level']})"
