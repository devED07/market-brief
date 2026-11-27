"""Headlines from Google News RSS (free, no key), tagged with simple
keyword rules so you can see why the headline tone leans one way."""

import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

from .config import DATA_DIR
from .util import atomic_write_json, make_session

QUERIES = [
    "gold price",
    "Federal Reserve OR Powell OR inflation OR Treasury yields",
    "Dow Jones OR Nasdaq OR S&P 500 OR Wall Street stocks",
    "tariffs OR war OR sanctions markets",
]

# Word lists are deliberately short and readable. Add your own.
TAGS = {
    "hawkish": [
        "hawkish", "rate hike", "hikes rates", "hotter inflation", "hotter cpi", "hotter ppi",
        "hotter data", "hotter jobs", "hotter pce", "hot inflation", "sticky inflation",
        "fewer cuts", "higher for longer", "yields jump", "yields rise", "yields climb",
        "yields surge", "dollar rises", "dollar gains", "dollar jumps", "strong jobs",
        "jobs beat", "inflation accelerat", "pushes back on cuts", "no rush to cut",
    ],
    "dovish": [
        "dovish", "rate cut", "cuts rates", "cooling inflation", "inflation cools", "inflation eases",
        "softer inflation", "softer cpi", "softer ppi", "softer jobs", "softer data", "softer pce",
        "slowdown", "weak jobs", "jobs miss", "layoffs", "yields fall", "yields drop",
        "yields slide", "dollar falls", "dollar slips", "dollar weakens", "recession",
    ],
    "risk-off": [
        "tariff", "sell-off", "selloff",
        "stocks fall", "stocks drop", "stocks slide", "stocks tumble", "stocks plunge",
        "dow falls", "dow drops", "dow slides", "dow tumbles", "dow sheds",
        "nasdaq falls", "nasdaq drops", "nasdaq slides", "nasdaq tumbles", "nasdaq sinks",
        "s&p falls", "s&p drops", "s&p slides", "tech stocks fall", "tech selloff", "tech sell-off",
        "crisis", "default", "bank run", "shutdown", "safe haven", "safe-haven", "turmoil",
    ],
    "risk-on": [
        "deal reached", "trade deal", "agreement reached",
        "stocks rise", "stocks rally", "stocks climb", "stocks gain", "stocks hit record",
        "dow rises", "dow climbs", "dow gains", "dow rallies", "dow hits record",
        "nasdaq rises", "nasdaq rallies", "nasdaq climbs", "nasdaq gains", "nasdaq hits record",
        "s&p rises", "s&p rallies", "s&p climbs", "s&p gains", "s&p hits record",
        "tech stocks rise", "tech stocks rally",
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

# Rate talk about other central banks shouldn't count as hawkish/dovish for the Fed,
# unless US / Fed context is explicitly present too.
NOT_US = re.compile(
    r"\b(india|indian|rbi|ecb|boj|bank of japan|boe|bank of england|rba|pboc|snb|"
    r"bank of canada|rbnz|japan|china|chinese|euro ?zone|uk|britain|australia)\b", re.I)
US_CTX = re.compile(
    r"\b(fed|federal reserve|fomc|powell|u\.s\.|us|united states|treasury|treasuries|"
    r"dollar|wall street|dow|nasdaq|s&p|cpi|pce|nfp|payrolls)\b", re.I)

_NEG_CUT = re.compile(
    r"\b(no|not|without|rules? out|delays?|push(?:es|ing)? back|fewer|less likely|trims?|par(?:e|es|ing)|skips?|pauses?)\b"
    r".{0,30}\b(rate[- ]cuts?|cuts? rates?)\b"
)
_NEG_RECESSION = re.compile(
    r"\b(avoids?|no|not|without|less likely)\b.{0,20}\brecession\b"
    r"|\brecession\b.{0,20}\b(fears? (?:fade|ease|recede)|averted)\b"
)
_NEG_DEAL = re.compile(
    r"\b(no|not|without)\b.{0,20}\b(trade deal|deal reached|agreement reached)\b"
    r"|\btrade deal\b.{0,20}\b(stalls?|collapses?|fails?|dead)\b"
)
_TARIFF_RELIEF = re.compile(
    r"\btariffs?\b.{0,25}\b(paus(?:e|es|ed|ing)|lift(?:s|ed|ing)?|delay(?:s|ed|ing)?|exempt(?:s|ed|ion)?|"
    r"dropp?(?:s|ed|ing)?|cut(?:s|ting)?|eas(?:e|es|ed|ing)|truce|rolled back)\b"
    r"|\b(paus(?:e|es|ed|ing)|lift(?:s|ed|ing)?|delay(?:s|ed|ing)?|drops?|cuts?|eases?)\b.{0,25}\btariffs?\b"
)

_STOPWORDS = frozenset({
    "the", "and", "for", "with", "from", "that", "this", "into", "over",
    "after", "amid", "says", "ahead", "are", "was", "were", "has", "have",
    "its", "will", "could", "would", "may", "but", "not", "out",
})


def _tag(title: str) -> list[str]:
    low = title.lower()
    matched = {tag: [w for w in words if _matches(w, low)] for tag, words in TAGS.items()}
    tag_set = {tag for tag, ms in matched.items() if ms}

    if _NEG_CUT.search(low):
        if set(matched["dovish"]) <= {"rate cut", "cuts rates"}:
            tag_set.discard("dovish")
        tag_set.add("hawkish")

    if _NEG_RECESSION.search(low) and set(matched["dovish"]) <= {"recession"}:
        tag_set.discard("dovish")

    if _NEG_DEAL.search(low) and set(matched["risk-on"]) <= {"deal reached", "trade deal", "agreement reached"}:
        tag_set.discard("risk-on")

    if _TARIFF_RELIEF.search(low):
        if set(matched["risk-off"]) <= {"tariff"}:
            tag_set.discard("risk-off")
        tag_set.add("risk-on")

    if NOT_US.search(title) and not US_CTX.search(title):
        tag_set.discard("hawkish")
        tag_set.discard("dovish")

    return [t for t in TAGS if t in tag_set]


def _trusted(source_url: str) -> bool:
    host = re.sub(r"^https?://", "", source_url or "").split("/")[0].lower()
    host = host[4:] if host.startswith("www.") else host
    return any(host == d or host.endswith("." + d) for d in TRUSTED)


def _tokens(title: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]{3,}", title.lower()) if w not in _STOPWORDS}


def _fetch_query(q: str, session) -> list[dict]:
    url = (
        "https://news.google.com/rss/search?q="
        + quote_plus(q + " when:1d")
        + "&hl=en-US&gl=US&ceid=US:en"
    )
    resp = None
    for wait in (0, 5):  # Google sometimes turns away GitHub's shared machines briefly
        if wait:
            time.sleep(wait)
        resp = session.get(url, timeout=20)
        if resp.status_code not in (429, 503):
            break
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
        link = (item.findtext("link") or "").strip()
        if not link.startswith(("http://", "https://")):
            link = ""
        items.append({
            "title": title,
            "source": source,
            "link": link,
            "time": published,
            "trusted": _trusted(source_url),
        })
    return items


def fetch_headlines(now: datetime | None = None, hours: int = 12, limit: int = 30) -> tuple[list[dict], list[str]]:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    session = make_session()
    raw: list[dict] = []
    problems: list[str] = []
    for q in QUERIES:
        try:
            for h in _fetch_query(q, session):
                if h["time"] >= cutoff and not JUNK.search(h["title"]):
                    raw.append(h)
        except Exception as exc:
            problems.append(f"News ({q.split(' OR ')[0]}): {exc.__class__.__name__} {str(exc)[:120]}")

    # Prefer trusted outlets and newer timestamps before deduplication
    raw.sort(key=lambda h: (not h.get("trusted"), -h["time"].timestamp()))
    seen_prefix: set[str] = set()
    kept_tokens: list[set[str]] = []
    found: list[dict] = []
    for h in raw:
        key = re.sub(r"[^a-z0-9]", "", h["title"].lower())[:60]
        if key in seen_prefix:
            continue
        tok = _tokens(h["title"])
        if tok and any(len(tok & prev) / len(tok | prev) >= 0.65 for prev in kept_tokens):
            continue
        seen_prefix.add(key)
        if tok:
            kept_tokens.append(tok)
        h["tags"] = _tag(h["title"])
        found.append(h)

    found.sort(key=lambda h: h["time"], reverse=True)
    out = [h for h in found if h.get("trusted")]
    if len(out) < MIN_TRUSTED:
        out += [h for h in found if not h.get("trusted")][: MIN_TRUSTED - len(out)]
        out.sort(key=lambda h: h["time"], reverse=True)
    return out[:limit], problems


CACHE_FILE = DATA_DIR / "headlines_cache.json"


def save_cache(headlines: list[dict], now: datetime) -> None:
    rows = [dict(h, time=h["time"].isoformat()) for h in headlines]
    atomic_write_json(CACHE_FILE, {"saved": now.isoformat(), "items": rows})


def _read_cache() -> tuple[datetime | None, list[dict]]:
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        saved, rows = (data.get("saved"), data.get("items", [])) if isinstance(data, dict) else (None, data)
        for r in rows:
            r["time"] = datetime.fromisoformat(r["time"])
        return (datetime.fromisoformat(saved) if saved else None), rows
    except Exception:
        return None, []


def load_cache(now: datetime, max_age_h: int = 3) -> list[dict]:
    """Last good headlines, used when Google News doesn't answer."""
    _, rows = _read_cache()
    if rows and now - max(r["time"] for r in rows) < timedelta(hours=max_age_h):
        return rows
    return []


def recent_cache(now: datetime, max_age_min: int = 25) -> list[dict]:
    """Headlines fetched in the last 25 minutes. With 15-minute updates, every
    other run reuses them, so Google News isn't asked too often."""
    saved, rows = _read_cache()
    if saved and rows and now - saved < timedelta(minutes=max_age_min):
        return rows
    return []


def tone(headlines: list[dict], now: datetime | None = None) -> dict:
    """Rates tone: + hawkish / - dovish. Risk tone: + risk-off / - risk-on.
    Both roughly between -1 and +1, with a 6h recency half-life when `now` is given."""
    count = {t: 0 for t in TAGS}
    wcount = {t: 0.0 for t in TAGS}
    for h in headlines:
        if now is not None and h.get("time") is not None:
            age_h = max(0.0, (now - h["time"]).total_seconds() / 3600.0)
            w = 0.5 ** (age_h / 6.0)
        else:
            w = 1.0
        for t in h.get("tags", []):
            if t in count:
                count[t] += 1
                wcount[t] += w
    rates = (wcount["hawkish"] - wcount["dovish"]) / (wcount["hawkish"] + wcount["dovish"] + 3)
    risk = (wcount["risk-off"] - wcount["risk-on"]) / (wcount["risk-off"] + wcount["risk-on"] + 3)
    return {"rates": rates, "risk": risk, "count": count}
