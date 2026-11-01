"""The bias engine. Plain rules, so you can always see why it says what it says.

Five drivers feed each instrument, each turned into signed points:

1. US data this week: for every big USD release, how did 10Y T-note futures
   and the dollar move in the 15 min after it (30-45 min for the Fed)?
   T-notes down + dollar up = the market read it as hawkish. Older releases
   count less (half weight after 3 days).
2. Dollar and yields over the last 24h.
3. Risk mood from the VIX (level and change).
4. Headline tone from keyword tags.
5. The instrument's own price trend (24h, 4h, and against its 5-day average).

Hawkish / USD-up pressure is bearish for gold and for US30.
Risk-off is bullish for gold (safe haven) and bearish for US30, except when
gold is falling along with stocks: then it's selling everything, and fear
isn't counted for gold.
Score runs from -10 (strongly bearish) to +10 (strongly bullish).
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .prices import pct, price_at

NEW_YORK = ZoneInfo("America/New_York")

ZN_BIG = 0.25        # % move in 10Y T-note futures that counts as a big reaction
DXY_BIG = 0.35       # % move in the dollar index that counts as big
HALF_LIFE_H = 72     # a release's influence halves every 3 days
YAHOO_DELAY_MIN = 12 # futures on Yahoo lag ~10 min, so wait before scoring


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _fmt_pct(x: float | None, digits: int = 2) -> str:
    return "n/a" if x is None else f"{x:+.{digits}f}%"


# ---------------------------------------------------------------- releases

def score_release(rel: dict, series: dict, now: datetime) -> dict:
    t = rel["time"]
    end = t + timedelta(minutes=rel["window_min"])
    out = dict(rel)
    out.update({"status": "upcoming", "hawk": None, "verdict": "", "zn_pct": None,
                "dxy_pct": None, "gold_pct": None, "us30_pct": None})

    if rel.get("all_day"):
        out["status"] = "all_day"
        return out
    if t > now:
        return out
    if now < end + timedelta(minutes=YAHOO_DELAY_MIN):
        out["status"] = "waiting"
        out["verdict"] = "Reading the reaction"
        return out

    out["status"] = "done"
    moves = {}
    for key in ("treasury_10y", "dollar", "gold", "us30"):
        s = series.get(key)
        moves[key] = pct(price_at(s, t), price_at(s, end)) if s is not None else None
    out["zn_pct"], out["dxy_pct"] = moves["treasury_10y"], moves["dollar"]
    out["gold_pct"], out["us30_pct"] = moves["gold"], moves["us30"]

    parts = []
    if out["zn_pct"] is not None:
        parts.append(-out["zn_pct"] / ZN_BIG)
    if out["dxy_pct"] is not None:
        parts.append(out["dxy_pct"] / DXY_BIG)
    if not parts:
        out["verdict"] = "No price data for that window"
        return out

    hawk = clamp(sum(parts) / len(parts), -2.0, 2.0)
    out["hawk"] = hawk
    if hawk >= 1.0:
        out["verdict"] = "Hawkish surprise"
    elif hawk >= 0.3:
        out["verdict"] = "Leaned hawkish"
    elif hawk <= -1.0:
        out["verdict"] = "Dovish surprise"
    elif hawk <= -0.3:
        out["verdict"] = "Leaned dovish"
    else:
        out["verdict"] = "In line, little reaction"
    return out


def data_score(releases: list[dict], now: datetime) -> tuple[float | None, str]:
    total, used, notes = 0.0, 0, []
    for r in releases:
        if r["status"] != "done" or r["hawk"] is None or r.get("lead_only"):
            continue
        age_h = (now - r["time"]).total_seconds() / 3600
        if age_h > 7 * 24:
            continue
        contrib = r["hawk"] * r["weight"] * 0.5 ** (age_h / HALF_LIFE_H)
        total += contrib
        used += 1
        notes.append((abs(contrib), r))
    if not used:
        return None, "No big US releases scored yet this week"
    notes.sort(key=lambda n: -n[0])
    lead = notes[0][1]
    scored = f"{used} release{'s' if used != 1 else ''} scored"
    detail = f"{scored}. Biggest: {_short(lead['headline'])}, {lead['verdict'].lower()}"
    return clamp(total, -2.0, 2.0), detail


def _short(title: str) -> str:
    return (title.replace(" m/m", "").replace(" y/y", "").replace(" q/q", "")
            .replace("Non-Farm Employment Change", "NFP"))


# ---------------------------------------------------------------- market context

def trend_score(snaps: dict) -> tuple[float | None, str]:
    parts, bits = [], []
    dx = snaps.get("dollar", {}).get("chg_24h")
    zn = snaps.get("treasury_10y", {}).get("chg_24h")
    if dx is not None:
        parts.append(clamp(dx / 0.5, -1.5, 1.5))
        bits.append(f"dollar {_fmt_pct(dx)}")
    if zn is not None:
        parts.append(clamp(-zn / 0.3, -1.5, 1.5))
        if abs(zn) < 0.05:
            bits.append("yields flat")
        else:
            bits.append("yields rising" if zn < 0 else "yields falling")
    if not parts:
        return None, "No dollar or yield data"
    return sum(parts) / len(parts), ", ".join(bits) + " (24h)"


def risk_score(snaps: dict) -> tuple[float | None, str]:
    v = snaps.get("vix")
    if not v:
        return None, "No VIX data"
    level, chg = v["last"], v.get("chg_24h")
    score = clamp((chg or 0) / 10, -1.0, 1.0)
    if level >= 25:
        score += 0.75
    elif level >= 20:
        score += 0.35
    elif level <= 14:
        score -= 0.3
    mood = "nervous" if score > 0.4 else "calm" if score < -0.2 else "steady"
    detail = f"VIX {level:.1f}"
    if chg is not None:
        detail += f", {chg:+.0f}% in 24h"
    return clamp(score, -1.5, 1.5), f"{detail}; mood {mood}"


# How big a move counts as one full point of trend (%), per instrument.
TREND_SCALE = {
    "gold": {"chg_24h": 1.5, "chg_4h": 0.6, "vs_5d": 2.0},
    "us30": {"chg_24h": 1.0, "chg_4h": 0.4, "vs_5d": 1.5},
}


def price_trend(key: str, snaps: dict) -> tuple[float | None, str]:
    """The instrument's own direction: last 24h, last 4h, and where it sits
    against its 5-day average. Roughly -1.5 (falling hard) to +1.5."""
    s = snaps.get(key)
    if not s:
        return None, "No price data"
    parts = []
    for field, w in (("chg_24h", 0.4), ("chg_4h", 0.3), ("vs_5d", 0.3)):
        v = s.get(field)
        if v is not None:
            parts.append((w, clamp(v / TREND_SCALE[key][field], -1.5, 1.5)))
    if not parts:
        return None, "Not enough price history"
    score = sum(w * x for w, x in parts) / sum(w for w, _ in parts)
    bits = []
    for field, label in (("chg_24h", "24h"), ("chg_4h", "4h")):
        if s.get(field) is not None:
            bits.append(f"{s[field]:+.1f}% in {label}")
    v5 = s.get("vs_5d")
    if v5 is not None:
        bits.append("above its 5-day average" if v5 > 0.15 else
                    "below its 5-day average" if v5 < -0.15 else "near its 5-day average")
    return score, ", ".join(bits)


def gold_risk(r: float, detail: str, snaps: dict) -> tuple[float, str]:
    """Fear only counts as safe-haven buying if gold is actually holding up.
    When gold falls along with stocks, traders are selling everything."""
    if r < 0.2:  # calm or barely moving: nothing to second-guess
        return r * 1.5, detail
    g = snaps.get("gold", {}).get("chg_24h")
    u = snaps.get("us30", {}).get("chg_24h")
    if g is None:
        return r * 1.5, detail
    if g <= -0.5 and u is not None and u < 0:
        return 0.0, detail + ". Gold fell with stocks, so it's selling everything, not safe-haven buying"
    if g < -0.2:
        return r * 0.75, detail + ". Gold is slipping, so only half counts"
    return r * 1.5, detail


# ---------------------------------------------------------------- instruments

def _label(score: float) -> tuple[str, str]:
    a = abs(score)
    if a < 1.5:
        return "No clear lean", "flat"
    side = "bullish" if score > 0 else "bearish"
    tone = "bull" if score > 0 else "bear"
    if a < 4:
        return f"Leaning {side}", tone
    if a < 7:
        return side.capitalize(), tone
    return f"Strongly {side}", tone


def _instrument(name: str, drivers: list[dict], trend: dict) -> dict:
    drivers = drivers + [trend]
    score = clamp(sum(d["points"] for d in drivers), -10.0, 10.0)
    label, tone = _label(score)

    # Do the news and data point one way while price goes the other?
    fundamentals = sum(d["points"] for d in drivers if d is not trend)
    warning = ""
    if abs(fundamentals) >= 1.5 and abs(trend["points"]) >= 0.8 and fundamentals * trend["points"] < 0:
        side = "bullish" if fundamentals > 0 else "bearish"
        move = "falling" if trend["points"] < 0 else "rising"
        warning = (f"Price disagrees. The data and news lean {side}, but {name} has been {move} "
                   f"({trend['detail']}). Let price confirm before leaning on this.")
    strong = [d for d in drivers if abs(d["points"]) >= 0.5]
    signs = {1 if d["points"] > 0 else -1 for d in strong}
    if not signs:
        agreement = "Nothing is pushing hard either way"
    elif len(strong) == 1:
        agreement = f"Mostly one driver: {strong[0]['name'].lower()}"
    elif len(signs) == 1:
        agreement = "Drivers agree"
    else:
        agreement = "Drivers are mixed, lower conviction"
    return {"score": score, "label": label, "tone": tone, "drivers": drivers,
            "agreement": agreement, "warning": warning}


def build(releases: list[dict], snaps: dict, headline_tone: dict, now: datetime) -> dict:
    d_score, d_detail = data_score(releases, now)
    t_score, t_detail = trend_score(snaps)
    r_score, r_detail = risk_score(snaps)
    h = headline_tone
    c = h["count"]
    h_detail = (f"{c['hawkish']} hawkish, {c['dovish']} dovish, "
                f"{c['risk-off']} risk-off, {c['risk-on']} risk-on")

    d, t, r = d_score or 0.0, t_score or 0.0, r_score or 0.0
    g_trend, g_trend_detail = price_trend("gold", snaps)
    u_trend, u_trend_detail = price_trend("us30", snaps)
    g_risk, g_risk_detail = gold_risk(r, r_detail, snaps)

    gold = _instrument("gold", [
        {"name": "US data this week", "points": -d * 2.0, "detail": d_detail},
        {"name": "Dollar and yields", "points": -t * 2.0, "detail": t_detail},
        {"name": "Risk mood", "points": g_risk, "detail": g_risk_detail},
        {"name": "Headlines", "points": -h["rates"] * 1.0 + h["risk"] * 1.0, "detail": h_detail},
    ], {"name": "Price trend", "points": (g_trend or 0.0) * 2.0, "detail": g_trend_detail})
    us30 = _instrument("US30", [
        {"name": "US data this week", "points": -d * 1.5, "detail": d_detail},
        {"name": "Dollar and yields", "points": -t * 1.5, "detail": t_detail},
        {"name": "Risk mood", "points": -r * 2.5, "detail": r_detail},
        {"name": "Headlines", "points": -h["rates"] * 0.8 - h["risk"] * 1.2, "detail": h_detail},
    ], {"name": "Price trend", "points": (u_trend or 0.0) * 2.0, "detail": u_trend_detail})
    return {"gold": gold, "us30": us30,
            "components": {"data": d_score, "trend": t_score, "risk": r_score,
                           "headline_rates": h["rates"], "headline_risk": h["risk"]}}


# ---------------------------------------------------------------- timing

def market_status(now: datetime, local_tz) -> dict:
    """Gold and Dow futures trade Sun 6pm to Fri 5pm New York time, with a
    one-hour break each day at 5pm New York."""
    ny = now.astimezone(NEW_YORK)
    wd = ny.weekday()  # Monday = 0
    weekend = wd == 5 or (wd == 4 and ny.hour >= 17) or (wd == 6 and ny.hour < 18)
    daily_break = not weekend and ny.hour == 17
    if weekend:
        days_to_sunday = (6 - wd) % 7
        reopen = (ny + timedelta(days=days_to_sunday)).replace(hour=18, minute=0, second=0, microsecond=0)
        return {"open": False, "reason": "weekend", "reopen": reopen.astimezone(local_tz)}
    if daily_break:
        reopen = ny.replace(hour=18, minute=0, second=0, microsecond=0)
        return {"open": False, "reason": "daily break", "reopen": reopen.astimezone(local_tz)}
    return {"open": True, "reason": "", "reopen": None}


def sessions_for_night(now: datetime, local_tz, market: dict | None = None) -> dict:
    """A 24h window in your time zone (6am to 6am) with the main sessions.
    Over the weekend it shows the first trading day after the reopen."""
    title = "Your trading day, 6am to 6am"
    if market and market.get("reason") == "weekend" and market.get("reopen"):
        now = market["reopen"] + timedelta(hours=1)
        title = f"{now.astimezone(local_tz):%A}'s trading day, 6am to 6am"
    local_now = now.astimezone(local_tz)
    start_day = local_now.date() if local_now.hour >= 6 else (local_now - timedelta(days=1)).date()
    win_start = datetime(start_day.year, start_day.month, start_day.day, 6, tzinfo=local_tz)
    win_end = win_start + timedelta(hours=24)

    defs = [
        ("Tokyo", "Asia/Tokyo", (9, 0), (15, 0)),
        ("London", "Europe/London", (8, 0), (16, 30)),
        ("New York", "America/New_York", (8, 0), (17, 0)),
        ("US30 cash", "America/New_York", (9, 30), (16, 0)),
    ]
    rows = []
    for name, tzname, (oh, om), (ch, cm) in defs:
        tz = ZoneInfo(tzname)
        for offset in (-1, 0, 1):
            day = (win_start.astimezone(tz) + timedelta(days=offset)).date()
            if day.weekday() >= 5:
                continue
            o = datetime(day.year, day.month, day.day, oh, om, tzinfo=tz).astimezone(local_tz)
            c = datetime(day.year, day.month, day.day, ch, cm, tzinfo=tz).astimezone(local_tz)
            if c <= win_start or o >= win_end:
                continue
            rows.append({"name": name, "open": max(o, win_start), "close": min(c, win_end)})
            break
    return {"start": win_start, "end": win_end, "sessions": rows, "title": title}
