"""Optional Telegram alerts. Off unless turned on in settings.ini."""

import json
from datetime import timedelta

import requests

from .config import DATA_DIR
from .leadup import one_line as leadup_line

STATE_FILE = DATA_DIR / "alert_state.json"


def _load_state() -> dict:
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        state = {}
    state.setdefault("labels", {})
    state.setdefault("sent", [])
    return state


def _save_state(state: dict) -> None:
    state["sent"] = state.get("sent", [])[-200:]
    STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


def send(settings, text: str) -> str | None:
    """Returns an error message, or None if it worked."""
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{settings.telegram_token}/sendMessage",
            data={"chat_id": settings.telegram_chat_id, "text": text,
                  "parse_mode": "HTML", "disable_web_page_preview": "true"},
            timeout=15,
        )
        if resp.status_code != 200:
            return f"Telegram said {resp.status_code}: {resp.text[:120]}"
    except Exception as exc:
        return f"Telegram unreachable ({exc.__class__.__name__})"
    return None


def _summary(brief: dict, tz) -> str:
    g, u = brief["bias"]["gold"], brief["bias"]["us30"]
    lines = [
        f"<b>Gold</b>: {g['label']} ({g['score']:+.1f})",
        f"<b>US30</b>: {u['label']} ({u['score']:+.1f})",
    ]
    nxt = brief.get("next_release")
    if nxt:
        t = nxt["time"].astimezone(tz)
        lines.append(f"Next: {nxt['headline']} at {t:%a} {t:%I:%M %p}".replace(" 0", " "))
    return "\n".join(lines)


def process(settings, brief: dict, now) -> str | None:
    if not settings.telegram_enabled:
        return None
    if not settings.telegram_token or not settings.telegram_chat_id:
        return "Telegram is on in settings.ini but bot_token or chat_id is empty."

    tz = settings.tz
    state = _load_state()
    messages = []
    if not state.get("labels"):
        messages.append("✅ Market Brief is connected. You'll get alerts here.")

    # 1. Bias changed since the last run
    changed = []
    for key, name in (("gold", "Gold"), ("us30", "US30")):
        label = brief["bias"][key]["label"]
        old = state["labels"].get(key)
        if old and old != label:
            changed.append(f"{name}: {old} → <b>{label}</b>")
        state["labels"][key] = label
    if changed:
        messages.append("Bias changed\n" + "\n".join(changed))

    # 2. Heads-up before high-impact releases (about 60 and 15 minutes out)
    for rel in brief["releases"]:
        if rel["impact"] != "High" or rel["status"] != "upcoming":
            continue
        mins = (rel["time"] - now).total_seconds() / 60
        mark = 15 if 0 < mins <= 20 else 60 if 0 < mins <= 65 else None
        key = f"{rel['time'].isoformat()}|{mark}"
        if mark and key not in state["sent"]:
            state["sent"].append(key)
            skip = f"{rel['time'].isoformat()}|60"
            if mark == 15 and skip not in state["sent"]:  # no point sending the 60-minute one late
                state["sent"].append(skip)
            when = rel["time"].astimezone(tz)
            extra = f" (forecast {rel['events'][0]['forecast']})" if rel["events"][0]["forecast"] else ""
            msg = f"⚠️ <b>{rel['headline']}</b>{extra} in {int(mins)} min, at {when:%I:%M %p}".replace("at 0", "at ")
            for read in brief.get("leadups", []):
                if read["release"]["time"] == rel["time"]:
                    msg += "\n" + leadup_line(read)
            messages.append(msg)

    # 3. Release scored
    for rel in brief["releases"]:
        if rel["status"] == "done" and rel["hawk"] is not None and rel["impact"] == "High":
            key = f"{rel['time'].isoformat()}|scored"
            age = now - rel["time"]
            if key not in state["sent"] and age < timedelta(hours=2):
                state["sent"].append(key)
                messages.append(
                    f"📊 {rel['headline']}: <b>{rel['verdict']}</b>\n"
                    f"Gold {rel['gold_pct'] or 0:+.2f}%, US30 {rel['us30_pct'] or 0:+.2f}% in the first {rel['window_min']} min"
                )

    if settings.telegram_every_update or messages:
        messages.append(_summary(brief, tz))

    error = None
    if messages:
        error = send(settings, "\n\n".join(messages))
    _save_state(state)
    return error
