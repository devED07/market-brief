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
HISTORY_PAGE_FILE = APP_DIR / "history.html"
LEVELS_PAGE_FILE = APP_DIR / "levels.html"


@dataclass
class Settings:
    refresh_minutes: int = 30
    timezone: str = "Asia/Manila"
    open_browser: bool = True

    gold: str = "GC=F"
    us30: str = "YM=F"
    us100: str = "NQ=F"
    dollar: str = "DX-Y.NYB"
    treasury_10y: str = "ZN=F"
    vix: str = "^VIX"

    oanda_api_key: str = ""
    oanda_env: str = "practice"
    oanda_gold: str = "XAU_USD"
    oanda_us30: str = "US30_USD"
    oanda_us100: str = "NAS100_USD"

    twelvedata_api_key: str = ""
    twelvedata_gold: str = "XAU/USD"
    twelvedata_us30: str = ""
    twelvedata_us100: str = ""

    fred_key: str = ""

    telegram_enabled: bool = False
    telegram_token: str = ""
    telegram_chat_id: str = ""
    telegram_every_update: bool = False
    telegram_brief_time: str = "20:30"

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

    for key in ("gold", "us30", "us100", "dollar", "treasury_10y", "vix"):
        val = (sym.get(key) or "").strip()
        if val:
            setattr(s, key, val)

    if cp.has_section("oanda"):
        oa = cp["oanda"]
        s.oanda_api_key = (oa.get("api_key") or "").strip()
        env_oa = (oa.get("env") or s.oanda_env).strip().lower()
        s.oanda_env = "live" if env_oa == "live" else "practice"
        for key, attr in (("gold", "oanda_gold"), ("us30", "oanda_us30"), ("us100", "oanda_us100")):
            val = (oa.get(key) or "").strip()
            if val:
                setattr(s, attr, val)

    if cp.has_section("twelvedata"):
        td = cp["twelvedata"]
        s.twelvedata_api_key = (td.get("api_key") or "").strip()
        for key, attr in (("gold", "twelvedata_gold"), ("us30", "twelvedata_us30"), ("us100", "twelvedata_us100")):
            if key in td:
                setattr(s, attr, (td.get(key) or "").strip())

    if cp.has_section("fred"):
        s.fred_key = (cp["fred"].get("api_key") or "").strip()

    s.telegram_enabled = _yes(tg.get("enabled", "no"))
    s.telegram_token = (tg.get("bot_token") or "").strip()
    s.telegram_chat_id = (tg.get("chat_id") or "").strip()
    s.telegram_every_update = _yes(tg.get("send_every_update", "no"))
    s.telegram_brief_time = (tg.get("brief_time") or s.telegram_brief_time).strip()

    # On GitHub the token comes from the repo's secret settings, never from
    # settings.ini (the repo is public). The chat id is optional: the bot finds
    # your chat when you press Start.
    env_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    env_chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if env_token:
        s.telegram_enabled = True
        s.telegram_token = env_token
        s.telegram_chat_id = env_chat

    env_oanda_key = os.environ.get("OANDA_API_KEY", "").strip()
    if env_oanda_key:
        s.oanda_api_key = env_oanda_key
    env_oanda_env = os.environ.get("OANDA_ENV", "").strip().lower()
    if env_oanda_env in ("practice", "live"):
        s.oanda_env = env_oanda_env

    env_td_key = os.environ.get("TWELVEDATA_API_KEY", "").strip()
    if env_td_key:
        s.twelvedata_api_key = env_td_key

    DATA_DIR.mkdir(exist_ok=True)
    return s
