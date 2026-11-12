"""Telegram bot: alerts and a daily session brief.

Setup on GitHub needs just one secret, TELEGRAM_BOT_TOKEN. Open your bot in
Telegram and press Start; the next update finds your chat and locks onto it.
(TELEGRAM_CHAT_ID still works if you'd rather set it yourself.)

The chat id is stored scrambled with your bot token, because the app's saved
state is published alongside the public dashboard.
"""

import hashlib
import json
import os
from datetime import datetime, timedelta

import requests

from .config import DATA_DIR
from .leadup import one_line as leadup_line

STATE_FILE = DATA_DIR / "alert_state.json"
API = "https://api.telegram.org/bot{token}/{method}"


# ------------------------------------------------------------------ state

def _load_state() -> dict:
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        state = {}
    state.setdefault("labels", {})
    state.setdefault("sent", [])
    return state


def _save_state(state: dict) -> None:
    state["sent"] = state.get("sent", [])[-300:]
    STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


def _key(token: str) -> bytes:
    return hashlib.sha256(b"market-brief-chat|" + token.encode()).digest()


def _scramble(chat_id: str, token: str) -> str:
    return bytes(a ^ b for a, b in zip(chat_id.encode(), _key(token))).hex()


def _unscramble(blob: str, token: str) -> str | None:
    try:
        return bytes(a ^ b for a, b in zip(bytes.fromhex(blob), _key(token))).decode()
    except Exception:
        return None


# ------------------------------------------------------------------ telegram calls

def _call(token: str, method: str, **params) -> dict:
    resp = requests.post(API.format(token=token, method=method), data=params, timeout=15)
    data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    if resp.status_code != 200 or not data.get("ok"):
        raise RuntimeError(f"Telegram said {resp.status_code}: {str(data.get('description', resp.text))[:120]}")
    return data


def send(token: str, chat_id: str, text: str) -> str | None:
    """Returns an error message, or None if it worked."""
    try:
        _call(token, "sendMessage", chat_id=chat_id, text=text, parse_mode="HTML",
              disable_web_page_preview="true")
    except Exception as exc:
        return str(exc) if isinstance(exc, RuntimeError) else f"Telegram unreachable ({exc.__class__.__name__})"
    return None


def _find_chat(token: str) -> str | None:
    """The most recent private chat that messaged the bot (e.g. pressed Start)."""
    try:
        updates = _call(token, "getUpdates", allowed_updates='["message"]').get("result", [])
    except Exception:
        return None
    for u in reversed(updates):
        chat = (u.get("message") or {}).get("chat") or {}
        if chat.get("type") == "private" and chat.get("id"):
            return str(chat["id"])
    return None


def _chat_id(settings, state: dict) -> tuple[str | None, bool]:
    """Returns (chat id, newly connected?)."""
    if settings.telegram_chat_id:
        return settings.telegram_chat_id, False
    blob = state.get("chat")
    if blob:
        cid = _unscramble(blob, settings.telegram_token)
        if cid and cid.lstrip("-").isdigit():
            return cid, False
    cid = _find_chat(settings.telegram_token)
    if cid:
        state["chat"] = _scramble(cid, settings.telegram_token)
        return cid, True
    return None, False


# ------------------------------------------------------------------ messages

def _dashboard_url() -> str:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" in repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner.lower()}.github.io/{name}/"
    return ""


def _t(dt: datetime, tz, fmt: str = "%I:%M %p") -> str:
    return dt.astimezone(tz).strftime(fmt).replace(" 0", " ").lstrip("0")


def _summary(brief: dict, tz) -> str:
    lines = [
        f"<b>{name}</b>: {inst['label']} ({inst['score']:+.1f})" + (", price disagrees" if inst.get("warning") else "")
        for name, inst in (("Gold", brief["bias"]["gold"]), ("US30", brief["bias"]["us30"]),
                           ("US100", brief["bias"]["us100"]))
    ]
    nxt = brief.get("next_release")
    if nxt:
        lines.append(f"Next: {nxt['headline']} on {_t(nxt['time'], tz, '%a')} at {_t(nxt['time'], tz)}")
    return "\n".join(lines)


def _top_drivers(inst: dict, n: int = 2) -> str:
    ds = sorted((d for d in inst["drivers"] if abs(d["points"]) >= 0.3), key=lambda d: -abs(d["points"]))[:n]
    if not ds:
        return "nothing pushing hard"
    return ", ".join(f"{d['name']} {d['points']:+.1f}" for d in ds)


def session_brief(brief: dict, tz, now: datetime) -> str:
    g, u, n = brief["bias"]["gold"], brief["bias"]["us30"], brief["bias"]["us100"]
    lines = [f"🗒 <b>Session brief</b>, {_t(now, tz, '%a %b %d')}", ""]
    for name, inst in (("Gold", g), ("US30", u), ("US100", n)):
        lines.append(f"<b>{name}</b>: {inst['label']} ({inst['score']:+.1f})")
        lines.append(f"   Driven by {_top_drivers(inst)}")
        if inst.get("warning"):
            lines.append("   ⚠️ Price disagrees with the data and news")
    geo = brief.get("geo")
    if geo:
        lines.append(f"Geopolitics: {geo['level']} ({geo['ratio']:.1f}x normal)")

    today = [r for r in brief["releases"]
             if r["status"] == "upcoming" and not r.get("lead_only") and not r.get("all_day")
             and r["time"] - now < timedelta(hours=14)]
    lines.append("")
    if today:
        lines.append("<b>Coming up</b>")
        for r in today[:6]:
            flag = "🔴" if r["impact"] == "High" else "🟠"
            lines.append(f"{flag} {_t(r['time'], tz)} {r['headline']}")
    else:
        lines.append("No big US releases in the next 14 hours.")
    for read in brief.get("leadups", []):
        lines.append(f"{read['target']['name']} ({_t(read['release']['time'], tz, '%a')}): {leadup_line(read)}")
    url = _dashboard_url()
    if url:
        lines += ["", f'<a href="{url}">Open the dashboard</a>']
    return "\n".join(lines)


def _brief_due(settings, state: dict, now: datetime) -> bool:
    local = now.astimezone(settings.tz)
    try:
        hh, mm = (int(x) for x in settings.telegram_brief_time.split(":"))
    except Exception:
        return False
    due = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
    key = f"brief|{local:%Y-%m-%d}"
    return (local.weekday() < 5 and due <= local < due + timedelta(hours=2)
            and key not in state["sent"])


# ------------------------------------------------------------------ main entry

def process(settings, brief: dict, now) -> str | None:
    if not settings.telegram_enabled:
        return None
    if not settings.telegram_token:
        return "Telegram is turned on but there's no bot token."

    tz = settings.tz
    state = _load_state()
    chat_id, new_chat = _chat_id(settings, state)
    if not chat_id:
        _save_state(state)
        return "Telegram bot is set up, but no chat yet. Open your bot in Telegram and press Start."

    messages = []
    if new_chat or not state.get("labels"):
        messages.append("✅ <b>Market Brief is connected.</b> You'll get release warnings, reaction "
                        "scores, bias changes, and a session brief each weekday evening.")

    # 1. Bias changed. A new label has to hold for two updates in a row
    # before it's announced, so a score hovering at a boundary doesn't ping
    # you every 15 minutes.
    changed = []
    pending = state.setdefault("pending", {})
    for key, name in (("gold", "Gold"), ("us30", "US30"), ("us100", "US100")):
        label = brief["bias"][key]["label"]
        old = state["labels"].get(key)
        if not old:
            state["labels"][key] = label
        elif label == old:
            pending.pop(key, None)
        elif pending.get(key) == label:
            changed.append(f"{name}: {old} → <b>{label}</b>")
            state["labels"][key] = label
            pending.pop(key, None)
        else:
            pending[key] = label
    if changed:
        messages.append("Bias changed\n" + "\n".join(changed))

    # 1b. Geopolitical tension just turned high
    geo = brief.get("geo")
    if geo:
        old_geo = state["labels"].get("geo")
        if geo["level"] == "high" and old_geo and old_geo != "high":
            messages.append(f"🌍 Geopolitical tension is <b>high</b>: conflict news at {geo['ratio']:.1f}x "
                            "its 30-day normal. Usually supportive for gold, a headwind for US30 and US100.")
        state["labels"]["geo"] = geo["level"]

    # 2. Heads-up before high-impact releases (about 60 and 15 minutes out)
    for rel in brief["releases"]:
        if rel["impact"] != "High" or rel["status"] != "upcoming" or rel.get("all_day"):
            continue
        mins = (rel["time"] - now).total_seconds() / 60
        mark = 15 if 0 < mins <= 20 else 60 if 0 < mins <= 65 else None
        key = f"{rel['time'].isoformat()}|{mark}"
        if mark and key not in state["sent"]:
            state["sent"].append(key)
            skip = f"{rel['time'].isoformat()}|60"
            if mark == 15 and skip not in state["sent"]:  # no point sending the 60-minute one late
                state["sent"].append(skip)
            extra = f" (forecast {rel['events'][0]['forecast']})" if rel["events"][0]["forecast"] else ""
            msg = f"⚠️ <b>{rel['headline']}</b>{extra} in {int(mins)} min, at {_t(rel['time'], tz)}"
            for read in brief.get("leadups", []):
                if read["release"]["time"] == rel["time"]:
                    msg += "\n" + leadup_line(read)
            messages.append(msg)

    # 3. Release scored
    for rel in brief["releases"]:
        if rel["status"] == "done" and rel["hawk"] is not None and rel["impact"] == "High":
            key = f"{rel['time'].isoformat()}|scored"
            if key not in state["sent"] and now - rel["time"] < timedelta(hours=2):
                state["sent"].append(key)
                messages.append(
                    f"📊 {rel['headline']}: <b>{rel['verdict']}</b>\n"
                    f"Gold {rel['gold_pct'] or 0:+.2f}%, US30 {rel['us30_pct'] or 0:+.2f}%, "
                    f"US100 {rel.get('us100_pct') or 0:+.2f}% "
                    f"in the first {rel['window_min']} min"
                )

    # 4. Session brief once each weekday evening
    if _brief_due(settings, state, now):
        state["sent"].append(f"brief|{now.astimezone(tz):%Y-%m-%d}")
        messages.append(session_brief(brief, tz, now))
    elif settings.telegram_every_update or messages:
        messages.append(_summary(brief, tz))

    error = None
    if messages:
        error = send(settings.telegram_token, chat_id, "\n\n".join(messages))
    _save_state(state)
    return error
