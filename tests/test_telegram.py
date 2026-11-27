from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from brief import telegram as T


def _settings(**kw):
    base = dict(
        tz=ZoneInfo("Asia/Manila"),
        telegram_enabled=True,
        telegram_token="12345:SECRET",
        telegram_chat_id="999999",
        telegram_every_update=False,
        telegram_brief_time="20:30",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _brief(now, gold_label="Bullish", headline="S&P <500> Flash PMI", forecast="<0.2%"):
    rel_t = now + timedelta(minutes=14)
    return {
        "bias": {
            "gold": {"label": gold_label, "score": 4.5, "drivers": [{"name": "Dollar and yields", "points": 2.0}]},
            "us30": {"label": "No clear lean", "score": 0.2, "drivers": []},
            "us100": {"label": "No clear lean", "score": -0.1, "drivers": []},
        },
        "geo": {"level": "normal", "ratio": 1.0},
        "releases": [{
            "time": rel_t, "impact": "High", "status": "upcoming", "all_day": False,
            "headline": headline, "window_min": 15,
            "events": [{"forecast": forecast}],
        }],
        "next_release": None,
        "leadups": [],
    }


def test_html_escaping_and_failed_send_retries(tmp_path, monkeypatch):
    state_file = tmp_path / "alert_state.json"
    monkeypatch.setattr(T, "STATE_FILE", state_file)

    now = datetime(2026, 11, 24, 10, 0, tzinfo=timezone.utc)
    sent_payloads = []
    fail_mode = {"fail": True}

    def fake_send(token, chat_id, text):
        sent_payloads.append(text)
        return "Telegram said 502" if fail_mode["fail"] else None

    monkeypatch.setattr(T, "send", fake_send)

    # First attempt fails -> error returned, `sent` and `labels` NOT committed
    err = T.process(_settings(), _brief(now), now)
    assert err == "Telegram said 502"
    state = T._load_state()
    assert state["sent"] == []
    assert state["labels"] == {}

    # Retry succeeds -> HTML escaped and state committed
    fail_mode["fail"] = False
    sent_payloads.clear()
    err2 = T.process(_settings(), _brief(now), now)
    assert err2 is None
    joined = "\n".join(sent_payloads)
    assert "S&amp;P &lt;500&gt; Flash PMI" in joined
    assert "&lt;0.2%" in joined
    state2 = T._load_state()
    assert any(k.endswith("|15") for k in state2["sent"])
    assert state2["labels"]["gold"] == "Bullish"


def test_hysteresis_and_chunking(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "STATE_FILE", tmp_path / "alert_state.json")
    now = datetime(2026, 11, 24, 10, 0, tzinfo=timezone.utc)

    # Seed initial state
    T._save_state({"labels": {"gold": "Bullish", "us30": "No clear lean", "us100": "No clear lean", "geo": "normal"}, "sent": []})

    sent_msgs = []
    monkeypatch.setattr(T, "send", lambda tok, cid, txt: sent_msgs.append(txt) or None)

    # Single-update flip sets pending without alerting
    b1 = _brief(now)
    b1["releases"] = []
    b1["bias"]["gold"]["label"] = "Leaning bullish"
    assert T.process(_settings(), b1, now) is None
    assert sent_msgs == []
    assert T._load_state()["pending"]["gold"] == "Leaning bullish"

    # Second consecutive update triggers alert
    assert T.process(_settings(), b1, now + timedelta(minutes=15)) is None
    assert len(sent_msgs) == 1
    assert "Bullish → <b>Leaning bullish</b>" in sent_msgs[0]

    # Chunking over MAX_MSG_LEN
    chunks = T._pack_chunks([{"text": "A" * 2500, "sent": ["k1"]}, {"text": "B" * 2500, "sent": ["k2"]}])
    assert len(chunks) == 2
    assert chunks[0]["sent"] == ["k1"] and chunks[1]["sent"] == ["k2"]


def test_scramble_and_connect_code(monkeypatch):
    tok = "123456:ABC"
    blob = T._scramble("987654321", tok)
    assert T._unscramble(blob, tok) == "987654321"

    monkeypatch.setenv("TELEGRAM_CONNECT_CODE", "mysecret")
    monkeypatch.setattr(T, "_call", lambda token, method, **kw: {
        "result": [
            {"message": {"chat": {"type": "private", "id": 111}, "text": "/start"}},
            {"message": {"chat": {"type": "private", "id": 222}, "text": "/start mysecret"}},
        ]
    })
    assert T._find_chat(tok) == "222"


def test_outage_alert_after_three_consecutive_problem_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "STATE_FILE", tmp_path / "alert_state.json")
    now = datetime(2026, 11, 24, 10, 0, tzinfo=timezone.utc)
    T._save_state({"labels": {"gold": "Flat", "us30": "No clear lean", "us100": "No clear lean", "geo": "normal"}, "sent": []})

    sent_msgs = []
    monkeypatch.setattr(T, "send", lambda tok, cid, txt: sent_msgs.append(txt) or None)

    b = _brief(now, gold_label="Flat")
    b["releases"] = []
    b["problems"] = ["Google News didn't respond"]

    assert T.process(_settings(), b, now) is None
    assert T.process(_settings(), b, now + timedelta(minutes=30)) is None
    assert sent_msgs == []  # only 2 failures so far

    assert T.process(_settings(), b, now + timedelta(minutes=60)) is None
    assert len(sent_msgs) == 1
    assert "Data feed issue" in sent_msgs[0]
    assert "3 runs in a row" in sent_msgs[0]

    # Run 4 within 6h does not spam
    sent_msgs.clear()
    assert T.process(_settings(), b, now + timedelta(minutes=90)) is None
    assert sent_msgs == []
