import subprocess
from datetime import datetime, timezone

import pandas as pd

import main as M
from brief import levels_page as LVL
from brief import prices as P
from brief import publish as PUB
from brief.config import load_settings


def test_session_levels_aligns_asia_evening_to_next_futures_day():
    # Futures session for 2026-11-24 starts 2026-11-23 18:00 ET
    # Completed day 2026-11-23 starts 2026-11-22 18:00 ET -> 2026-11-23 16:55 ET
    bars = []
    vals = []

    # Previous completed day: 2026-11-22 18:00 ET .. 2026-11-23 16:55 ET
    prev_start = pd.Timestamp("2026-11-22 18:00", tz="America/New_York").tz_convert("UTC")
    for i, ts in enumerate(pd.date_range(prev_start, periods=276, freq="5min")):
        bars.append(ts)
        vals.append(4100.0 + (i % 30))

    # Current day: 2026-11-23 18:00 ET .. 2026-11-24 10:00 ET (covers Asia + London + NY)
    cur_start = pd.Timestamp("2026-11-23 18:00", tz="America/New_York").tz_convert("UTC")
    for i, ts in enumerate(pd.date_range(cur_start, periods=193, freq="5min")):
        bars.append(ts)
        vals.append(4200.0 + i * 0.5)

    series = pd.Series(vals, index=pd.DatetimeIndex(bars))
    sl = P.session_levels(series)

    assert sl["pdh"] == 4129.0
    assert sl["pdl"] == 4100.0
    assert sl["pdc"] == vals[275]
    assert sl["today_open"] == 4200.0
    assert sl["asia_h"] is not None and sl["asia_l"] is not None
    assert sl["london_h"] is not None and sl["london_l"] is not None
    assert sl["ny_h"] is not None and sl["ny_l"] is not None
    assert sl["prev_asia_h"] is not None
    assert sl["week_h"] == 4129.0

    dl = P.daily_levels(series, days=5)
    assert len(dl) == 1
    assert dl[0]["date"] == "2026-11-23"


def test_levels_page_renders_tabs_and_3page_nav(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "DASHBOARD_FILE", tmp_path / "dashboard.html")
    monkeypatch.setattr(M, "HISTORY_PAGE_FILE", tmp_path / "history.html")
    monkeypatch.setattr(M, "LEVELS_PAGE_FILE", tmp_path / "levels.html")

    settings = load_settings()
    brief, _ = M.run_cycle(settings, demo=True, memory={})
    html = brief["levels_html"]

    assert 'href="dashboard.html"' in html
    assert 'href="levels.html"' in html
    assert 'href="history.html"' in html
    assert 'id="lvl-gold"' in html
    assert 'id="lvl-us30"' in html
    assert 'id="lvl-us100"' in html
    assert "Current session levels" in html
    assert "PDH (Previous Day High)" in html
    assert "PDH / PDL" in html
    assert "Asia High (18–03 ET)" in html

    brief["hosted"] = True
    hosted_html = LVL.render(brief)
    assert 'href="index.html"' in hosted_html


def test_publish_pushes_levels_and_history_to_gh_pages(tmp_path, monkeypatch):
    remote_dir = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote_dir)], check=True, capture_output=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(PUB, "DATA_DIR", data_dir)
    monkeypatch.setenv("MB_PUBLISH_REMOTE", str(remote_dir))

    PUB.publish("<html>live</html>", 2000, "Test pub",
                history_html="<html>hist</html>", levels_html="<html>lvls</html>")
    r = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "gh-pages"],
        cwd=remote_dir, capture_output=True, text=True, check=True,
    )
    assert sorted(r.stdout.strip().splitlines()) == [
        ".nojekyll", "history.html", "index.html", "levels.html", "meta.json",
    ]
