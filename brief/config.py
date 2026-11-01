"""Reads settings.ini so the rest of the app doesn't have to."""

import configparser
import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "data"
SETTINGS_FILE = APP_DIR / "settings.ini"
DASHBOARD_FILE = APP_DIR / "dashboard.html"


@dataclass
class Settings:
    refresh_minutes: int = 30
    timezone: str = "Asia/Manila"
    open_browser: bool = True

    gold: str = "GC=F"
    us30: str = "YM=F"
    dollar: str = "DX-Y.NYB"
    treasury_10y: str = "ZN=F"
    vix: str = "^VIX"

    telegram_enabled: bool = False
    telegram_token: str = ""
    telegram_chat_id: str = ""
    telegram_every_update: bool = False

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


def _yes(value: str) -> bool:
    return str(value).strip().lower() in ("yes", "y", "true", "1", "on")


def load_settings() -> Settings:
    s = Settings()
    cp = configparser.ConfigParser(inline_comment_prefixes=(";", "#"))
    if SETTINGS_FILE.exists():
        cp.read(SETTINGS_FILE, encoding="utf-8")

    app = cp["app"] if cp.has_section("app") else {}
    sym = cp["symbols"] if cp.has_section("symbols") else {}
    tg = cp["telegram"] if cp.has_section("telegram") else {}

    try:
        s.refresh_minutes = max(5, int(app.get("refresh_minutes", s.refresh_minutes)))
    except ValueError:
        pass
    s.timezone = (app.get("timezone") or s.timezone).strip()
    try:
        ZoneInfo(s.timezone)
    except Exception:
        print(f"  ! Unknown timezone '{s.timezone}' in settings.ini, using Asia/Manila")
        s.timezone = "Asia/Manila"
    s.open_browser = _yes(app.get("open_browser", "yes"))

    for key in ("gold", "us30", "dollar", "treasury_10y", "vix"):
        val = (sym.get(key) or "").strip()
        if val:
            setattr(s, key, val)

    s.telegram_enabled = _yes(tg.get("enabled", "no"))
    s.telegram_token = (tg.get("bot_token") or "").strip()
    s.telegram_chat_id = (tg.get("chat_id") or "").strip()
    s.telegram_every_update = _yes(tg.get("send_every_update", "no"))

    # On GitHub the token and chat id come from the repo's secret settings,
    # never from settings.ini (the repo is public).
    env_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    env_chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if env_token and env_chat:
        s.telegram_enabled = True
        s.telegram_token = env_token
        s.telegram_chat_id = env_chat

    DATA_DIR.mkdir(exist_ok=True)
    return s
