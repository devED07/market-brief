from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import main as M
from brief import bias as B
from brief import publish as PUB


def test_next_run_time_and_stay_until():
    tz = ZoneInfo("Asia/Manila")
    settings = SimpleNamespace(refresh_minutes=30, tz=tz)
    now = datetime(2026, 11, 25, 13, 0, tzinfo=timezone.utc)
    fomc_t = now + timedelta(minutes=30)
    releases = [
        {"time": fomc_t, "impact": "High", "status": "upcoming", "all_day": False, "lead_only": False, "window_min": 45},
    ]
    nxt = M.next_run_time(now, settings, releases)
    # 16 minutes before FOMC (now + 14m) beats regular xx:32 slot (now + 32m)
    assert nxt == fomc_t - timedelta(minutes=16)

    until = M._stay_until(releases, now)
    assert until == fomc_t + timedelta(minutes=45 + B.YAHOO_DELAY_MIN + 2)


def test_update_score_history_prunes_and_throttles(tmp_path, monkeypatch):
    hist_file = tmp_path / "score_history.json"
    monkeypatch.setattr(M, "SCORE_HISTORY_FILE", hist_file)
    now = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)
    bias = {"gold": {"score": 3.5}, "us30": {"score": -2.1}, "us100": {"score": -1.4}}

    rows1 = M.update_score_history(bias, now - timedelta(hours=50), persist=True)
    assert len(rows1) == 1
    # 2 minutes later is throttled (<5 min); old 50h point is pruned
    rows2 = M.update_score_history(bias, now, persist=True)
    assert len(rows2) == 1
    rows3 = M.update_score_history(bias, now + timedelta(minutes=2), persist=True)
    assert len(rows3) == 1
    rows4 = M.update_score_history(bias, now + timedelta(minutes=6), persist=True)
    assert len(rows4) == 2


def test_apply_fred_fallback_and_discrepancy():
    rels = [
        {"status": "done", "hawk": None, "verdict": "No price data", "data": {"CPI m/m": {"z": 1.4, "text": "0.4%"}}},
        {"status": "done", "hawk": -1.2, "verdict": "Dovish surprise", "data": {"NFP": {"z": 1.3, "text": "280K"}}},
    ]
    B.apply_fred_fallback(rels)
    assert rels[0]["hawk"] == 1.4
    assert rels[0]["verdict"] == "Hawkish surprise (FRED)"
    assert rels[1]["discrepancy"] == "Market went opposite the print"


def test_run_hosted_stay_on_recovers_after_transient_error(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "DATA_DIR", tmp_path)
    monkeypatch.setattr(PUB, "restore_state", lambda: "ok")
    monkeypatch.setattr(PUB, "publish", lambda *a, **kw: None)
    fake_now = {"t": datetime(2026, 11, 25, 13, 0, tzinfo=timezone.utc)}

    class FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fake_now["t"] if tz is None else fake_now["t"].astimezone(tz)

    def fake_sleep(secs):
        fake_now["t"] += timedelta(seconds=secs)

    monkeypatch.setattr(M, "datetime", FakeDatetime)
    monkeypatch.setattr(M.time, "sleep", fake_sleep)

    rel_t = fake_now["t"] + timedelta(minutes=10)
    calls = {"n": 0}

    def fake_cycle(settings, demo, memory, hosted=False):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("transient yahoo glitch")
        status = "upcoming" if calls["n"] == 1 else "done"
        brief = {
            "now": fake_now["t"],
            "bias": {
                "gold": {"label": "Flat", "score": 0.0},
                "us30": {"label": "Flat", "score": 0.0},
                "us100": {"label": "Flat", "score": 0.0},
            },
            "next_release": None,
            "geo": None,
            "problems": [],
            "releases": [{
                "time": rel_t, "impact": "High", "status": status,
                "all_day": False, "lead_only": False, "window_min": 15,
                "headline": "CPI m/m",
            }],
        }
        return brief, "<html></html>"

    monkeypatch.setattr(M, "run_cycle", fake_cycle)
    settings = SimpleNamespace(tz=ZoneInfo("Asia/Manila"), refresh_minutes=30, telegram_enabled=False)
    M.run_hosted(settings)
    assert calls["n"] == 3
    assert (tmp_path / "error.log").exists()
