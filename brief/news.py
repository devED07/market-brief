"""Headlines from Google News RSS (free, no key), tagged with simple
keyword rules so you can see why the headline tone leans one way."""

import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import requests

from .config import DATA_DIR

QUERIES = [
    "gold price",
    "Federal Reserve OR Powell OR inflation OR Treasury yields",
    "Dow Jones OR Wall Street stocks",
    "tariffs OR war OR sanctions markets",
]
HEADERS = {"User-Agent": "Mozilla/5.0 (personal market brief app)"}

# Word lists are deliberately short and readable. Add your own.
TAGS = {
    "hawkish": [
        "hawkish", "rate hike", "hikes rates", "hotter", "hot inflation", "sticky inflation",
        "fewer cuts", "higher for longer", "yields jump", "yields rise", "yields climb",
        "yields surge", "dollar rises", "dollar gains", "dollar jumps", "strong jobs",
        "jobs beat", "inflation accelerat", "pushes back on cuts", "no rush to cut",
    ],
    "dovish": [
        "dovish", "rate cut", "cuts rates", "cooling inflation", "inflation cools", "inflation eases",
        "softer", "slowdown", "weak jobs", "jobs miss", "layoffs", "yields fall", "yields drop",
        "yields slide", "dollar falls", "dollar slips", "dollar weakens", "recession",
    ],
    "risk-off": [
        "tariff", "sell-off", "selloff",
        "stocks fall", "stocks drop", "stocks slide", "stocks tumble", "stocks plunge",
        "dow falls", "dow drops", "dow slides", "dow tumbles", "dow sheds", "crisis",
        "default", "bank run", "shutdown", "safe haven", "safe-haven", "turmoil",
    ],
    "risk-on": [
        "deal reached", "trade deal", "agreement reached",
        "stocks rise", "stocks rally", "stocks climb", "stocks gain", "stocks hit record",
        "dow rises", "dow climbs", "dow gains", "dow rallies", "dow hits record",
    ],
    # Shown on headlines for context. The Geopolitics driver itself comes from
    # GDELT (geo.py), so these don't add to the headline score.
    "geopolitics": [
        "war", "missile", "attack", "airstrike", "air strike", "escalat", "sanction", "conflict",
        "invasion", "invade", "troops", "nuclear", "terror", "drone strike",
    ],
    "de-escalation": [
        "ceasefire", "truce", "peace talks", "peace deal", "eases tensions", "tensions ease",
        "de-escalat",
    ],
}


def _matches(word: str, text: str) -> bool:
    # Short words must match whole ("war" but not "warns"); longer ones can
    # be word starts ("escalat" matches "escalation").
    pattern = r"(?<![a-z])" + re.escape(word)
    if len(word) <= 4:
        pattern += r"s?(?![a-z])"
    return re.search(pattern, text) is not None


# Major market news outlets. Headlines from these come first; others only
# fill in if there are too few.
TRUSTED = (
    "reuters.com", "bloomberg.com", "cnbc.com", "wsj.com", "ft.com", "marketwatch.com",
    "barrons.com", "apnews.com", "kitco.com", "fxstreet.com", "investing.com", "forexlive.com",
    "finance.yahoo.com", "axios.com", "nytimes.com", "washingtonpost.com", "theguardian.com",
    "bbc.com", "bbc.co.uk", "cnn.com", "foxbusiness.com", "economist.com", "politico.com",
    "morningstar.com", "nasdaq.com", "investopedia.com", "businessinsider.com", "thestreet.com",
)
MIN_TRUSTED = 8

# Local jewellery prices and similar stories that don't move XAUUSD or the Dow.
JUNK = re.compile(
    r"(\b(18|22|24)k\b|gold rate|rates? today|jewel|delhi|mumbai|chennai|kolkata|hyderabad|"
    r"bengaluru|karachi|lahore|real estate|gold coast)", re.I)

# Rate talk about other central banks shouldn't count as hawkish/dovish for the Fed.
NOT_US = re.compile(
    r"\b(india|indian|rbi|ecb|boj|bank of japan|boe|bank of england|rba|pboc|snb|"
    r"bank of canada|rbnz|japan|china|chinese|euro ?zone|uk|britain|australia)\b", re.I)


def _tag(title: str) -> list[str]:
    low = title.lower()
    tags = [tag for tag, words in TAGS.items() if any(_matches(w, low) for w in words)]
    if NOT_US.search(title):
        tags = [t for t in tags if t not in ("hawkish", "dovish")]
    return tags


def _trusted(source_url: str) -> bool:
    host = re.sub(r"^https?://", "", source_url or "").split("/")[0].lower()
    host = host[4:] if host.startswith("www.") else host
    return any(host == d or host.endswith("." + d) for d in TRUSTED)


def _fetch_query(q: str) -> list[dict]:
    url = (
        "https://news.google.com/rss/search?q="
        + quote_plus(q + " when:1d")
        + "&hl=en-US&gl=US&ceid=US:en"
    )
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    items = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        source_el = item.find("source")
        source = (source_el.text or "").strip() if source_el is not None else ""
        source_url = source_el.get("url", "") if source_el is not None else ""
        if source and title.endswith(" - " + source):
            title = title[: -len(" - " + source)]
        try:
            published = parsedate_to_datetime(item.findtext("pubDate") or "").astimezone(timezone.utc)
        except Exception:
            continue
        items.append({
            "title": title,
            "source": source,
            "link": (item.findtext("link") or "").strip(),
            "time": published,
            "trusted": _trusted(source_url),
        })
    return items


def fetch_headlines(now: datetime | None = None, hours: int = 12, limit: int = 30) -> tuple[list[dict], list[str]]:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    seen, found, problems = set(), [], []
    for q in QUERIES:
        try:
            for h in _fetch_query(q):
                key = re.sub(r"[^a-z0-9]", "", h["title"].lower())[:60]
                if key in seen or h["time"] < cutoff or JUNK.search(h["title"]):
                    continue
                seen.add(key)
                h["tags"] = _tag(h["title"])
                found.append(h)
        except Exception as exc:
            problems.append(f"News ({q.split(' OR ')[0]}): {exc.__class__.__name__} {str(exc)[:120]}")
    found.sort(key=lambda h: h["time"], reverse=True)
    out = [h for h in found if h.get("trusted")]
    if len(out) < MIN_TRUSTED:
        out += [h for h in found if not h.get("trusted")][: MIN_TRUSTED - len(out)]
        out.sort(key=lambda h: h["time"], reverse=True)
    return out[:limit], problems


CACHE_FILE = DATA_DIR / "headlines_cache.json"


def save_cache(headlines: list[dict]) -> None:
    rows = [dict(h, time=h["time"].isoformat()) for h in headlines]
    CACHE_FILE.write_text(json.dumps(rows), encoding="utf-8")


def load_cache(now: datetime, max_age_h: int = 3) -> list[dict]:
    """Last good headlines, used when Google News doesn't answer."""
    try:
        rows = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        for r in rows:
            r["time"] = datetime.fromisoformat(r["time"])
        if rows and now - max(r["time"] for r in rows) < timedelta(hours=max_age_h):
            return rows
    except Exception:
        pass
    return []


def tone(headlines: list[dict]) -> dict:
    """Rates tone: + hawkish / - dovish. Risk tone: + risk-off / - risk-on.
    Both roughly between -1 and +1."""
    count = {t: 0 for t in TAGS}
    for h in headlines:
        for t in h.get("tags", []):
            count[t] += 1
    rates = (count["hawkish"] - count["dovish"]) / (count["hawkish"] + count["dovish"] + 3)
    risk = (count["risk-off"] - count["risk-on"]) / (count["risk-off"] + count["risk-on"] + 3)
    return {"rates": rates, "risk": risk, "count": count}
