import subprocess
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

import main as M
from brief import bias as B
from brief import history_page as H
from brief import leadup as L
from brief import prices as P
from brief import publish as PUB
from brief.config import load_settings


def test_daily_levels_returns_5_completed_days_with_sessions():
    # Build 6 NY trading days (00:00..16:55 NY)
    bars = []
    vals = []
    for day_offset in range(6):
        day_start = pd.Timestamp(f"2026-11-{16 + day_offset} 00:00", tz="America/New_York").tz_convert("UTC")
        day_idx = pd.date_range(day_start, periods=204, freq="5min")
        for idx_i, ts in enumerate(day_idx):
            bars.append(ts)
            vals.append(4000.0 + day_offset * 10.0 + (idx_i % 20))

    series = pd.Series(vals, index=pd.DatetimeIndex(bars))
    levels = P.daily_levels(series, days=5)
    assert len(levels) == 5
    # Newest completed day first (Nov 20, since Nov 21 is current incomplete day)
    assert levels[0]["date"] == "2026-11-20"
    assert levels[-1]["date"] == "2026-11-16"
    for row in levels:
        assert row["high"] >= row["low"]
        assert row["london_h"] is not None and row["london_l"] is not None
        assert row["ny_h"] is not None and row["ny_l"] is not None


def test_score_release_computes_1h_follow_through_and_log_persists(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "LOG_FILE", tmp_path / "release_log.json")
    t0 = datetime(2026, 11, 20, 13, 30, tzinfo=timezone.utc)
    idx = pd.date_range(t0 - timedelta(minutes=15), t0 + timedelta(minutes=75), freq="5min", tz="UTC")
    # 15m after t0: gold +0.5%, 60m after t0: gold -0.3% (reversal)
    gold_vals = []
    zn_vals = []
    for ts in idx:
        if ts < t0:
            gold_vals.append(4000.0)
            zn_vals.append(110.0)
        elif ts < t0 + timedelta(minutes=30):
            gold_vals.append(4020.0)
            zn_vals.append(109.7)
        else:
            gold_vals.append(3988.0)
            zn_vals.append(110.2)
    series = {
        "gold": pd.Series(gold_vals, index=idx),
        "us30": pd.Series(gold_vals, index=idx),
        "us100": pd.Series(gold_vals, index=idx),
        "treasury_10y": pd.Series(zn_vals, index=idx),
    }
    rel = {
        "time": t0,
        "headline": "CPI m/m",
        "window_min": 15,
        "weight": 1.5,
        "impact": "High",
        "lead_only": False,
        "events": [{"title": "CPI m/m", "forecast": "0.3%", "previous": "0.2%", "actual": "0.4%"}],
    }
    scored = B.score_release(rel, series, t0 + timedelta(minutes=75))
    assert scored["gold_pct"] is not None and scored["gold_pct"] > 0.4
    assert scored["gold_1h_pct"] is not None and scored["gold_1h_pct"] < -0.2

    rows = L.update_log([scored], t0 + timedelta(minutes=80), persist=True)
    assert len(rows) == 1
    assert rows[0]["actual"] == "0.4%"
    assert rows[0]["forecast"] == "0.3%"
    assert rows[0]["previous"] == "0.2%"
    assert rows[0]["gold_1h_pct"] == scored["gold_1h_pct"]


def test_history_page_renders_levels_releases_and_nav(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "DASHBOARD_FILE", tmp_path / "dashboard.html")
    monkeypatch.setattr(M, "HISTORY_PAGE_FILE", tmp_path / "history.html")
    settings = load_settings()
    brief, dash_html = M.run_cycle(settings, demo=True, memory={})
    hist_html = brief["history_html"]

    assert 'href="history.html"' in dash_html
    assert 'href="dashboard.html"' in hist_html
    assert "PDH / PDL" in hist_html
    assert 'id="lvl-gold"' in hist_html
    assert 'id="lvl-us30"' in hist_html
    assert 'id="lvl-us100"' in hist_html
    assert "ISM Services PMI" in hist_html
    assert "Bullish" in hist_html or "Bearish" in hist_html

    # Hosted mode links to index.html and shows Reversed badge when 1h flips
    brief["hosted"] = True
    brief["release_log"].append({
        "time": datetime(2026, 11, 20, 13, 30, tzinfo=timezone.utc),
        "headline": "Core CPI m/m",
        "impact": "High",
        "lead_only": False,
        "hawk": 1.2,
        "verdict": "Hawkish surprise",
        "actual": "0.4%",
        "forecast": "0.3%",
        "previous": "0.3%",
        "gold_pct": -0.55,
        "gold_1h_pct": 0.25,
        "us30_pct": -0.40,
        "us30_1h_pct": -0.60,
        "us100_pct": -0.70,
        "us100_1h_pct": -0.90,
        "discrepancy": "",
    })
    hosted_hist = H.render(brief)
    assert 'href="index.html"' in hosted_hist
    assert "Reversed" in hosted_hist


def test_publish_includes_history_html_without_state(tmp_path, monkeypatch):
    remote_dir = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote_dir)], check=True, capture_output=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(PUB, "DATA_DIR", data_dir)
    monkeypatch.setenv("MB_PUBLISH_REMOTE", str(remote_dir))

    PUB.publish("<html>live</html>", 2000, "Test pub", history_html="<html>hist</html>")
    r = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "gh-pages"],
        cwd=remote_dir, capture_output=True, text=True, check=True,
    )
    assert sorted(r.stdout.strip().splitlines()) == [".nojekyll", "history.html", "index.html", "meta.json"]
