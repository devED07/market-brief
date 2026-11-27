"""Geopolitical tension from the GDELT Project's live event feed (free, open).

Every 15 minutes GDELT publishes a small file of world events it found in the
news, each coded by type (threats, military posturing, coercion, attacks,
fighting...) and by the countries involved. For events between two different
countries, we measure conflict-weighted coverage in the last 24 hours compared
with the normal level over the past 30 days.

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
from .util import atomic_write_json, thread_session

HOST_PATH = "data.gdeltproject.org/gdeltv2"
FEED = f"https://{HOST_PATH}/{{stamp}}.export.CSV.zip"
LAST_UPDATE = f"https://{HOST_PATH}/lastupdate.txt"
HISTORY_FILE = DATA_DIR / "geo_history.json"
CACHE_FILE = DATA_DIR / "geo_cache.json"

SCHEMA_VERSION = 2
KEEP_DAYS = 31
BACKFILL_STEP_H = 4      # first run: one file every 4 hours over 30 days (~180 files)
MAX_NEW_FILES = 24       # per run, newest first (6 hours of 15-min slots)
BACKFILL_CHUNK = 60
MATERIAL_CONFLICT = {"18", "19", "20"}   # assault, fight, mass violence
VERBAL_CONFLICT = {"13", "15", "17"}     # threaten, military posture, coerce
CONFLICT_ROOTS = MATERIAL_CONFLICT | VERBAL_CONFLICT

# GDELT 2.0 event columns we use
COL_ACTOR1_COUNTRY, COL_ACTOR2_COUNTRY = 7, 17
COL_ROOT, COL_QUAD, COL_GOLDSTEIN, COL_ARTICLES = 28, 29, 30, 33

LEVELS = [  # (ratio at or above, label)
    (1.4, "high"),
    (1.15, "elevated"),
    (0.85, "normal"),
    (0.0, "quieter than usual"),
]

_preferred_scheme = "https"


def _get(path_or_url: str, timeout: int) -> requests.Response:
    """Fetch via HTTPS first, falling back to HTTP if TLS/connection fails."""
    global _preferred_scheme
    session = thread_session()
    rel = path_or_url.split("://", 1)[-1]
    schemes = [_preferred_scheme] + [s for s in ("https", "http") if s != _preferred_scheme]
    last_exc: Exception | None = None
    for scheme in schemes:
        try:
            resp = session.get(f"{scheme}://{rel}", timeout=timeout)
            _preferred_scheme = scheme
            return resp
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
            last_exc = exc
    raise last_exc  # type: ignore[misc]


def _stamp(t: datetime) -> str:
    return t.strftime("%Y%m%d%H%M%S")


def _parse(stamp: str) -> datetime:
    return datetime.strptime(stamp, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def _slot(t: datetime) -> datetime:
    return t.replace(minute=t.minute - t.minute % 15, second=0, microsecond=0)


def _latest_slot() -> datetime:
    resp = _get(LAST_UPDATE, timeout=20)
    resp.raise_for_status()
    for part in resp.text.split():
        if part.endswith(".export.CSV.zip"):
            return _parse(part.rsplit("/", 1)[-1].split(".")[0])
    raise ValueError("couldn't read GDELT's latest update")


def count_events(raw: str) -> tuple[int, int]:
    """(conflict score, total articles) for events between two countries.

    Material conflict (assault/fight/mass violence) counts 2x; verbal conflict
    counts 1x, with coercion (root 17) requiring GoldsteinScale <= -4.0.
    Syndicated article count per row is capped at 20.
    """
    conflict = total = 0
    for row in csv.reader(io.StringIO(raw), delimiter="\t"):
        if len(row) <= COL_ARTICLES:
            continue
        a, b = row[COL_ACTOR1_COUNTRY], row[COL_ACTOR2_COUNTRY]
        if not a or not b or a == b:
            continue
        try:
            n = min(max(1, int(row[COL_ARTICLES] or 1)), 20)
        except ValueError:
            n = 1
        total += n
        root = row[COL_ROOT]
        if root in MATERIAL_CONFLICT:
            conflict += 2 * n
        elif root in VERBAL_CONFLICT:
            if root == "17":
                try:
                    goldstein = float(row[COL_GOLDSTEIN])
                except (ValueError, IndexError):
                    continue
                if goldstein > -4.0:
                    continue
            conflict += n
    return conflict, total


def _download(slot: datetime) -> tuple[int, int] | None:
    resp = _get(FEED.format(stamp=_stamp(slot)), timeout=30)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        names = z.namelist()
        if not names:
            return None
        raw = z.read(names[0]).decode("utf-8", errors="replace")
    counts = count_events(raw)
    return counts if counts[1] > 0 else None


def _load_history() -> dict[str, list[int]]:
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("v") == SCHEMA_VERSION and isinstance(data.get("slots"), dict):
            return data["slots"]
        return {}  # Reset legacy v1 history so baseline and recent share the v2 metric
    except Exception:
        return {}


def _save_history(hist: dict[str, list[int]]) -> None:
    atomic_write_json(HISTORY_FILE, {"v": SCHEMA_VERSION, "slots": hist})


def update_history(now: datetime) -> dict[str, list[int]]:
    hist = _load_history()
    cutoff = now - timedelta(days=KEEP_DAYS)
    hist = {k: v for k, v in hist.items() if _parse(k) >= cutoff}
    latest = _latest_slot()

    wanted: list[datetime] = []
    # New files since the last run, newest first; stop at the first known slot.
    t = latest
    while len(wanted) < MAX_NEW_FILES and t > now - timedelta(hours=26):
        if _stamp(t) in hist:
            break
        wanted.append(t)
        t -= timedelta(minutes=15)

    def safe(slot: datetime):
        try:
            return slot, _download(slot), True
        except Exception:
            return slot, None, False

    if wanted:
        with ThreadPoolExecutor(max_workers=6) as pool:
            for slot, counts, ok in pool.map(safe, wanted):
                if ok:
                    hist[_stamp(slot)] = list(counts) if counts else [0, 0]

    # First run (or schema upgrade / partial backfill): sample the past 30 days in chunks
    valid_days = {k[:8] for k, v in hist.items() if v and v[1] > 0}
    if len(valid_days) < 20:
        backfill: list[datetime] = []
        t = _slot(latest - timedelta(hours=BACKFILL_STEP_H))
        while t > now - timedelta(days=30):
            if _stamp(t) not in hist:
                backfill.append(t)
            t -= timedelta(hours=BACKFILL_STEP_H)
        for i in range(0, len(backfill), BACKFILL_CHUNK):
            chunk = backfill[i: i + BACKFILL_CHUNK]
            with ThreadPoolExecutor(max_workers=6) as pool:
                for slot, counts, ok in pool.map(safe, chunk):
                    if ok:
                        hist[_stamp(slot)] = list(counts) if counts else [0, 0]
            _save_history(hist)

    _save_history(hist)
    return hist


def summarize(hist: dict[str, list[int]], now: datetime) -> dict:
    recent_c = recent_t = 0
    days: dict[str, list[int]] = {}
    for stamp, (c, tot) in hist.items():
        if tot <= 0:
            continue
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
        atomic_write_json(CACHE_FILE, summary)
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
