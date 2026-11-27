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
from .util import atomic_write_json

LOG_FILE = DATA_DIR / "release_log.json"
KEEP_DAYS = 180

_DOMINANT_TITLES = (
    "non-farm", "cpi", "federal funds", "fomc", "pce", "gdp",
    "retail sales", "ism manufacturing", "ism services", "jolts", "powell",
)

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
        "lookback_days": 18,
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


def _lead_matches(rel: dict, target: dict) -> list[tuple[str, float, str]]:
    """All distinct lead-in definitions matched by this release group."""
    if _is_target(rel, target):
        return []
    titles = _titles(rel)
    by_name: dict[str, tuple[str, float, str]] = {}
    for word, name, weight in target["leads"]:
        if any(word in t for t in titles):
            prev = by_name.get(name)
            if prev is None or weight > prev[1]:
                by_name[name] = (name, weight, word)
    return list(by_name.values())


def _lead_value(entry: dict, word: str) -> tuple[float | None, str]:
    """The lead-in's surprise: actual vs forecast if FRED had the number,
    otherwise the market's reaction (unless an unrelated top-tier release
    at the same timestamp dominates the reaction). Returns (value, text)."""
    hits = [(title, d) for title, d in (entry.get("data") or {}).items() if word in title.lower()]
    if hits:
        value = sum(d["z"] for _, d in hits) / len(hits)
        if len(hits) == 1:
            return value, hits[0][1]["text"]
        return value, ", ".join(f"{t.replace(' m/m', '')} {d['text'].replace(' forecast', '')}" for t, d in hits)

    headline = (entry.get("headline") or "").lower()
    if headline and word not in headline:
        if word.startswith("ism ") and headline.startswith(word.rsplit(" ", 1)[0]):
            return entry.get("hawk"), "ISM report reaction"
        if any(k in headline for k in _DOMINANT_TITLES):
            return None, ""
    return entry.get("hawk"), ""


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
    """Adds newly scored releases to the log (merging with prior data) and returns the full log."""
    log = {r["time"].isoformat(): r for r in (load_log() if persist else [])}
    for rel in releases:
        if rel.get("status") != "done":
            continue
        key = rel["time"].isoformat()
        prev = log.get(key, {})
        merged_data = {**(prev.get("data") or {}), **(rel.get("data") or {})}
        hawk = rel["hawk"] if rel.get("hawk") is not None else prev.get("hawk")
        verdict = rel["verdict"] if rel.get("hawk") is not None else (prev.get("verdict") or rel.get("verdict", ""))
        if hawk is None and not merged_data:
            continue
        events = rel.get("events") or []
        ev0 = events[0] if events else {}
        actual = ev0.get("actual") or next((e.get("actual") for e in events if e.get("actual")), "") or prev.get("actual", "")
        forecast = ev0.get("forecast", "") or prev.get("forecast", "")
        previous = ev0.get("previous", "") or prev.get("previous", "")

        def _pick(field: str):
            val = rel.get(field)
            return val if val is not None else prev.get(field)

        log[key] = {
            "time": rel["time"],
            "headline": rel["headline"],
            "titles": [e["title"] for e in events] or prev.get("titles", []),
            "hawk": hawk,
            "verdict": verdict,
            "data": merged_data,
            "weight": rel.get("weight", prev.get("weight", 1.0)),
            "impact": rel.get("impact", prev.get("impact", "High")),
            "lead_only": rel.get("lead_only", prev.get("lead_only", False)),
            "window_min": rel.get("window_min", prev.get("window_min", 15)),
            "forecast": forecast,
            "previous": previous,
            "actual": actual,
            "zn_pct": _pick("zn_pct"),
            "dxy_pct": _pick("dxy_pct"),
            "gold_pct": _pick("gold_pct"),
            "us30_pct": _pick("us30_pct"),
            "us100_pct": _pick("us100_pct"),
            "gold_1h_pct": _pick("gold_1h_pct"),
            "us30_1h_pct": _pick("us30_1h_pct"),
            "us100_1h_pct": _pick("us100_1h_pct"),
            "discrepancy": rel.get("discrepancy") or prev.get("discrepancy", ""),
        }
    rows = sorted((r for r in log.values() if now - r["time"] < timedelta(days=KEEP_DAYS)),
                  key=lambda r: r["time"])
    if persist:
        atomic_write_json(LOG_FILE, [dict(r, time=r["time"].isoformat()) for r in rows])
    return rows


# ------------------------------------------------------------------ reads

def _collapse_repeats(items: list[dict]) -> list[dict]:
    """Collapse repeated prints of the same weekly series into one weighted entry."""
    grouped: dict[str, list[dict]] = {}
    for item in items:
        grouped.setdefault(item["name"], []).append(item)
    out: list[dict] = []
    for group in grouped.values():
        if len(group) == 1:
            out.append(group[0])
            continue
        group.sort(key=lambda x: x["time"])
        latest = group[-1]
        avg_hawk = sum(x["hawk"] for x in group) / len(group)
        base_text = latest.get("text") or latest.get("verdict") or ""
        text = f"{base_text} ({len(group)} prints)" if base_text else f"{len(group)} prints"
        out.append({
            "name": latest["name"],
            "weight": latest["weight"],
            "time": latest["time"],
            "hawk": avg_hawk,
            "verdict": latest.get("verdict", ""),
            "text": text,
        })
    out.sort(key=lambda x: x["time"])
    return out


def _read_one(target: dict, rel: dict, log: list[dict], releases: list[dict], now: datetime,
              extras: list[dict]) -> dict:
    start = rel["time"] - timedelta(days=target["lookback_days"])
    raw_scored, pending = [], []
    for entry in log:
        if start <= entry["time"] < rel["time"]:
            for name, weight, word in _lead_matches(entry, target):
                value, text = _lead_value(entry, word)
                if value is None:
                    continue
                raw_scored.append({"name": name, "weight": weight, "time": entry["time"],
                                   "hawk": value, "verdict": entry.get("verdict", ""), "text": text})
    for x in extras:  # leads that aren't calendar events, such as gasoline prices
        if x["key"] == target["key"] and start <= x["time"] < rel["time"]:
            raw_scored.append(dict(x))
    for r in releases:
        if r["status"] in ("upcoming", "waiting") and start <= r["time"] < rel["time"] and not r.get("all_day"):
            for name, weight, _word in _lead_matches(r, target):
                pending.append({"name": name, "weight": weight, "time": r["time"], "status": r["status"]})

    scored = _collapse_repeats(raw_scored)

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
        out["confidence"] = "Mostly priced in (CPI/PPI set the forecast)"
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
    conf = read["confidence"]
    conf_txt = (conf[:1].lower() + conf[1:]) if conf else ""
    text = f"Lead-up: {label} ({conf_txt})." if conf_txt else f"Lead-up: {label}."
    if read.get("side"):
        text += f" Usual first reaction if so: {reaction_text(read['target'], read['side'])}."
    return text
