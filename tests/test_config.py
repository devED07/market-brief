from brief import config as CFG


def test_load_settings_parses_ini_and_env_precedence(tmp_path, monkeypatch):
    ini = tmp_path / "settings.ini"
    ini.write_text(
        "[app]\nrefresh_minutes = 2\ntimezone = Invalid/Zone\nopen_browser = no\n"
        "[symbols]\ngold = XAUUSD=X\n"
        "[oanda]\napi_key = ini-oanda\nenv = practice\ngold = XAU_USD\nus30 = US30_USD\nus100 = NAS100_USD\n"
        "[fred]\napi_key = ini-fred\n"
        "[telegram]\nenabled = no\nbot_token = ini-tok\nchat_id = 111\nsend_every_update = yes\nbrief_time = 21:15\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(CFG, "SETTINGS_FILE", ini)
    monkeypatch.setattr(CFG, "DATA_DIR", tmp_path / "data")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.delenv("OANDA_API_KEY", raising=False)
    monkeypatch.delenv("OANDA_ENV", raising=False)

    s = CFG.load_settings()
    assert s.refresh_minutes == 5  # floored at 5
    assert s.timezone == "Asia/Manila"  # invalid tz fallback
    assert s.open_browser is False
    assert s.gold == "XAUUSD=X"
    assert s.oanda_api_key == "ini-oanda"
    assert s.oanda_env == "practice"
    assert s.oanda_gold == "XAU_USD"
    assert s.oanda_us30 == "US30_USD"
    assert s.oanda_us100 == "NAS100_USD"
    assert s.fred_key == "ini-fred"
    assert s.telegram_enabled is False
    assert s.telegram_every_update is True
    assert s.telegram_brief_time == "21:15"

    # Env vars override ini for hosted secrets
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env-tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "222")
    monkeypatch.setenv("OANDA_API_KEY", "env-oanda")
    monkeypatch.setenv("OANDA_ENV", "live")
    s2 = CFG.load_settings()
    assert s2.telegram_enabled is True
    assert s2.telegram_token == "env-tok"
    assert s2.telegram_chat_id == "222"
    assert s2.oanda_api_key == "env-oanda"
    assert s2.oanda_env == "live"
