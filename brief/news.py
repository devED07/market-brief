"""Headlines from Google News RSS (free, no key), tagged with simple
keyword rules so you can see why the headline tone leans one way."""

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import requests

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
        "war", "missile", "attack", "escalat", "sanction", "tariff", "sell-off", "selloff",
        "stocks fall", "stocks drop", "stocks slide", "stocks tumble", "stocks plunge",
        "dow falls", "dow drops", "dow slides", "dow tumbles", "dow sheds", "crisis",
        "default", "bank run", "shutdown", "conflict", "safe haven", "safe-haven", "turmoil",
    ],
    "risk-on": [
        "ceasefire", "truce", "deal reached", "trade deal", "agreement reached",
        "stocks rise", "stocks rally", "stocks climb", "stocks gain", "stocks hit record",
        "dow rises", "dow climbs", "dow gains", "dow rallies", "dow hits record",
        "eases tensions", "tensions ease",
    ],
}


def _matches(word: str, text: str) -> bool:
    # Short words must match whole ("war" but not "warns"); longer ones can
    # be word starts ("escalat" matches "escalation").
    pattern = r"(?<![a-z])" + re.escape(word)
    if len(word) <= 4:
        pattern += r"s?(?![a-z])"
    return re.search(pattern, text) is not None


def _tag(title: str) -> list[str]:
    low = title.lower()
    return [tag for tag, words in TAGS.items() if any(_matches(w, low) for w in words)]


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
        source = (item.findtext("source") or "").strip()
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
        })
    return items


def fetch_headlines(now: datetime | None = None, hours: int = 12, limit: int = 30) -> tuple[list[dict], list[str]]:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    seen, out, problems = set(), [], []
    for q in QUERIES:
        try:
            for h in _fetch_query(q):
                key = re.sub(r"[^a-z0-9]", "", h["title"].lower())[:60]
                if key in seen or h["time"] < cutoff:
                    continue
                seen.add(key)
                h["tags"] = _tag(h["title"])
                out.append(h)
        except Exception as exc:
            problems.append(f"News ({q.split(' OR ')[0]}): {exc.__class__.__name__}")
    out.sort(key=lambda h: h["time"], reverse=True)
    return out[:limit], problems


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
