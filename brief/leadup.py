"""Lead-up reads: what the smaller releases before a big one hint about it.

Example: ISM, JOLTS, ADP and jobless claims come out before NFP. If they
mostly surprised hot, there's a tilt toward a strong NFP too.

The free calendar has no actual numbers, so each lead-in is read from how
the market reacted to it (the same verdict as the release list): yields and
the dollar up = it came in hot, down = it came in cold. Weights say how much
each lead-in tends to tell you about the big one. Scored releases are kept
for 45 days, so lead-ins from earlier weeks still count.
"""

import json
from datetime import datetime, timedelta

from .config import DATA_DIR

LOG_FILE = DATA_DIR / "release_log.json"
KEEP_DAYS = 45

TARGETS = [
    {
        "key": "nfp",
        "name": "NFP",
        "match": "non-farm employment change",
        "not": "adp",
        "lookback_days": 12,
        "leads": [  # (title contains, short name, weight)
            ("adp non-farm", "ADP jobs", 0.5),
            ("unemployment claims", "Jobless claims", 0.4),
            ("ism services pmi", "ISM services", 0.4),
            ("ism manufacturing pmi", "ISM manufacturing", 0.3),
            ("jolts", "JOLTS job openings", 0.3),
            ("adp weekly", "ADP weekly jobs", 0.2),
            ("challenger", "Challenger job cuts", 0.2),
            ("cb consumer confidence", "Consumer confidence", 0.2),
        ],
        "hot": "a strong NFP",
        "cold": "a weak NFP",
        "note": "Earlier jobs data only loosely predicts NFP, and ADP is a weak guide month to month. "
                "Treat this as a tilt, not a call.",
    },
    {
        "key": "cpi",
        "name": "CPI",
        "match": "cpi",
        "not": None,
        "lookback_days": 25,
        "leads": [
            ("ppi", "PPI", 0.4),
            ("ism services prices", "ISM services prices", 0.3),
            ("ism manufacturing prices", "ISM manufacturing prices", 0.3),
            ("import prices", "Import prices", 0.3),
            ("average hourly earnings", "Wage growth (from NFP)", 0.3),
            ("inflation expectations", "Inflation expectations", 0.2),
        ],
        "hot": "a hot CPI",
        "cold": "a cool CPI",
        "note": "Price gauges in ISM and PPI give a partial read. Gasoline prices also matter a lot, "
                "and they aren't tracked here.",
    },
    {
        "key": "pce",
        "name": "Core PCE",
        "match": "pce price index",
        "not": None,
        "lookback_days": 25,
        "leads": [
            ("cpi", "CPI", 1.0),
            ("ppi", "PPI", 0.7),
            ("import prices", "Import prices", 0.2),
        ],
        "hot": "a hot PCE",
        "cold": "a cool PCE",
        "note": "Forecasters build the PCE forecast from CPI and PPI, so most of this is usually "
                "already in the forecast. Big PCE surprises are rare.",
    },
]

ALL_LEAD_WORDS = tuple({lead[0] for t in TARGETS for lead in t["leads"]})


def is_lead_in(title: str) -> bool:
    low = title.lower()
    return any(w in low for w in ALL_LEAD_WORDS)


def _titles(rel: dict) -> list[str]:
    return [t.lower() for t in rel.get("titles") or [e["title"] for e in rel["events"]]]


def _is_target(rel: dict, target: dict) -> bool:
    return any(target["match"] in t and not (target["not"] and target["not"] in t) for t in _titles(rel))


def _lead_match(rel: dict, target: dict) -> tuple[str, float] | None:
    best = None
    for word, name, weight in target["leads"]:
        if any(word in t for t in _titles(rel)) and not _is_target(rel, target):
            if best is None or weight > best[1]:
                best = (name, weight)
    return best


# ------------------------------------------------------------------ log

def load_log() -> list[dict]:
    try:
        rows = json.loads(LOG_FILE.read_text(encoding="utf-8"))
        for r in rows:
            r["time"] = datetime.fromisoformat(r["time"])
        return rows
    except Exception:
        return []


def update_log(releases: list[dict], now: datetime, persist: bool = True) -> list[dict]:
    """Adds newly scored releases to the log and returns the full log."""
    log = {r["time"].isoformat(): r for r in (load_log() if persist else [])}
    for rel in releases:
        if rel.get("status") != "done" or rel.get("hawk") is None:
            continue
        log[rel["time"].isoformat()] = {
            "time": rel["time"],
            "headline": rel["headline"],
            "titles": [e["title"] for e in rel["events"]],
            "hawk": rel["hawk"],
            "verdict": rel["verdict"],
        }
    rows = sorted((r for r in log.values() if now - r["time"] < timedelta(days=KEEP_DAYS)),
                  key=lambda r: r["time"])
    if persist:
        LOG_FILE.write_text(json.dumps([dict(r, time=r["time"].isoformat()) for r in rows]),
                            encoding="utf-8")
    return rows


# ------------------------------------------------------------------ reads

def _read_one(target: dict, rel: dict, log: list[dict], releases: list[dict], now: datetime) -> dict:
    start = rel["time"] - timedelta(days=target["lookback_days"])
    scored, pending = [], []
    for entry in log:
        if start <= entry["time"] < rel["time"]:
            m = _lead_match(entry, target)
            if m:
                scored.append({"name": m[0], "weight": m[1], "time": entry["time"],
                               "hawk": entry["hawk"], "verdict": entry["verdict"]})
    for r in releases:
        if r["status"] in ("upcoming", "waiting") and r["time"] < rel["time"] and not r.get("all_day"):
            m = _lead_match(r, target)
            if m:
                pending.append({"name": m[0], "weight": m[1], "time": r["time"], "status": r["status"]})

    out = {"target": target, "release": rel, "scored": scored, "pending": pending,
           "lean": None, "label": "Nothing to go on yet", "tone": "flat", "confidence": ""}
    if not scored:
        if pending:
            out["label"] = "Waiting for the lead-in data"
        return out

    total_w = sum(s["weight"] for s in scored)
    lean = sum(s["hawk"] * s["weight"] for s in scored) / total_w
    out["lean"] = lean
    strong = [s for s in scored if abs(s["hawk"]) >= 0.3]
    agree = (max(sum(1 for s in strong if s["hawk"] > 0), sum(1 for s in strong if s["hawk"] < 0))
             / len(strong)) if strong else 0

    if abs(lean) < 0.3:
        out["label"] = "Mixed or in line, no clear tilt"
    else:
        side = target["hot"] if lean > 0 else target["cold"]
        out["label"] = f"{'Points to' if abs(lean) >= 0.8 else 'Leans toward'} {side}"
        out["tone"] = "bear" if lean > 0 else "bull"

    if target["key"] == "pce" and any(s["name"] == "CPI" for s in scored):
        out["confidence"] = "Fairly reliable"
    elif len(strong) >= 2 and agree >= 0.67 and total_w >= 0.8:
        out["confidence"] = "Moderate confidence"
    else:
        out["confidence"] = "Low confidence"
    return out


def build(releases: list[dict], log: list[dict], now: datetime) -> list[dict]:
    """One read per upcoming NFP / CPI / PCE in the calendar."""
    reads = []
    for rel in releases:
        if rel["status"] != "upcoming" or rel.get("all_day"):
            continue
        for target in TARGETS:
            if _is_target(rel, target):
                reads.append(_read_one(target, rel, log, releases, now))
                break
    return reads


def one_line(read: dict) -> str:
    """Short text for Telegram."""
    if read["lean"] is None:
        return f"Lead-up: {read['label'].lower()}."
    return f"Lead-up: {read['label'].lower()} ({read['confidence'].lower()})."
