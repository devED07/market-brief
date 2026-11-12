"""Lead-up reads: what the smaller releases before a big one hint about it.

Example: ISM, JOLTS, ADP and jobless claims come out before NFP. If they
mostly surprised hot, there's a tilt toward a strong NFP too.

Each lead-in is read from its actual number against the forecast when FRED
has it (see fred.py). Otherwise it is read from how the market reacted to it
(the same verdict as the release list): yields and the dollar up = it came
in hot, down = it came in cold. Weights say how much
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
        # Usual first reaction to a strong number: +1 up, -1 down, 0 mixed.
        "if_hot": {"gold": -1.0, "us30": 0.0, "us100": -0.5},
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
        "if_hot": {"gold": -1.0, "us30": -1.0, "us100": -1.0},
        "note": "Price gauges in ISM and PPI give a partial read. Gasoline prices also matter a lot; "
                "they are included when the FRED key is set.",
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
        "if_hot": {"gold": -1.0, "us30": -1.0, "us100": -1.0},
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
                best = (name, weight, word)
    return best


def _lead_value(entry: dict, word: str) -> tuple[float | None, str]:
    """The lead-in's surprise: actual vs forecast if FRED had the number,
    otherwise the market's reaction. Returns (value, numbers to show)."""
    hits = [(title, d) for title, d in (entry.get("data") or {}).items() if word in title.lower()]
    if not hits:
        return entry.get("hawk"), ""
    value = sum(d["z"] for _, d in hits) / len(hits)
    if len(hits) == 1:
        return value, hits[0][1]["text"]
    return value, ", ".join(f"{t.replace(' m/m', '')} {d['text'].replace(' forecast', '')}" for t, d in hits)


def reaction_text(target: dict, side: str) -> str:
    """'gold down, US30 mixed, US100 leans down' for a hot or cold outcome."""
    flip = 1 if side == "hot" else -1
    bits = []
    for key, name in (("gold", "gold"), ("us30", "US30"), ("us100", "US100")):
        v = target["if_hot"][key] * flip
        word = "mixed" if abs(v) < 0.25 else ("up" if v > 0 else "down")
        bits.append(f"{name} {'leans ' if 0.25 <= abs(v) < 0.75 else ''}{word}")
    return ", ".join(bits)


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
        data = rel.get("data") or {}
        if rel.get("status") != "done" or (rel.get("hawk") is None and not data):
            continue
        log[rel["time"].isoformat()] = {
            "time": rel["time"],
            "headline": rel["headline"],
            "titles": [e["title"] for e in rel["events"]],
            "hawk": rel["hawk"],
            "verdict": rel["verdict"],
            "data": data,
        }
    rows = sorted((r for r in log.values() if now - r["time"] < timedelta(days=KEEP_DAYS)),
                  key=lambda r: r["time"])
    if persist:
        LOG_FILE.write_text(json.dumps([dict(r, time=r["time"].isoformat()) for r in rows]),
                            encoding="utf-8")
    return rows


# ------------------------------------------------------------------ reads

def _read_one(target: dict, rel: dict, log: list[dict], releases: list[dict], now: datetime,
              extras: list[dict]) -> dict:
    start = rel["time"] - timedelta(days=target["lookback_days"])
    scored, pending = [], []
    for entry in log:
        if start <= entry["time"] < rel["time"]:
            m = _lead_match(entry, target)
            if m:
                value, text = _lead_value(entry, m[2])
                if value is None:
                    continue
                scored.append({"name": m[0], "weight": m[1], "time": entry["time"],
                               "hawk": value, "verdict": entry.get("verdict", ""), "text": text})
    for x in extras:  # leads that aren't calendar events, such as gasoline prices
        if x["key"] == target["key"] and x["time"] < rel["time"]:
            scored.append(dict(x))
    for r in releases:
        if r["status"] in ("upcoming", "waiting") and r["time"] < rel["time"] and not r.get("all_day"):
            m = _lead_match(r, target)
            if m:
                pending.append({"name": m[0], "weight": m[1], "time": r["time"], "status": r["status"]})

    out = {"target": target, "release": rel, "scored": scored, "pending": pending,
           "lean": None, "side": None, "label": "Nothing to go on yet", "tone": "flat", "confidence": ""}
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
        out["side"] = "hot" if lean > 0 else "cold"

    if target["key"] == "pce" and any(s["name"] == "CPI" for s in scored):
        out["confidence"] = "Fairly reliable"
    elif len(strong) >= 2 and agree >= 0.67 and total_w >= 0.8:
        out["confidence"] = "Moderate confidence"
    else:
        out["confidence"] = "Low confidence"
    return out


def build(releases: list[dict], log: list[dict], now: datetime, extras: list[dict] | None = None) -> list[dict]:
    """One read per upcoming NFP / CPI / PCE in the calendar."""
    reads = []
    for rel in releases:
        if rel["status"] != "upcoming" or rel.get("all_day"):
            continue
        for target in TARGETS:
            if _is_target(rel, target):
                reads.append(_read_one(target, rel, log, releases, now, extras or []))
                break
    return reads


def one_line(read: dict) -> str:
    """Short text for Telegram."""
    label = read["label"][:1].lower() + read["label"][1:]
    if read["lean"] is None:
        return f"Lead-up: {label}."
    text = f"Lead-up: {label} ({read['confidence'].lower()})."
    if read.get("side"):
        text += f" Usual first reaction if so: {reaction_text(read['target'], read['side'])}."
    return text
