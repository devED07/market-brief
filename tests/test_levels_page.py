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
    assert dl[0]["open"] == 4100.0
    assert dl[0]["high_t"] and dl[0]["low_t"]
    assert dl[0]["asia_h_t"] and dl[0]["london_h_t"] and dl[0]["ny_h_t"]

    cur = P.current_day_levels(series)
    assert cur is not None and cur["is_today"] is True
    assert cur["date"] == "2026-11-24"
    assert cur["asia_h_t"] and cur["london_h_t"] and cur["ny_h_t"]


def test_levels_page_renders_tabs_and_3page_nav(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "DASHBOARD_FILE", tmp_path / "dashboard.html")
    monkeypatch.setattr(M, "HISTORY_PAGE_FILE", tmp_path / "history.html")
    monkeypatch.setattr(M, "LEVELS_PAGE_FILE", tmp_path / "levels.html")

    settings = load_settings()
    brief, dash_html = M.run_cycle(settings, demo=True, memory={})
    html = brief["levels_html"]

    assert 'href="levels.html#gold"' in dash_html
    assert 'href="levels.html#us30"' in dash_html
    assert 'href="levels.html#us100"' in dash_html

    assert 'href="dashboard.html"' in html
    assert 'href="levels.html"' in html
    assert 'href="history.html"' in html
    assert 'id="lvl-gold"' in html
    assert 'id="lvl-us30"' in html
    assert 'id="lvl-us100"' in html
    assert "Today (Live)" in html
    assert "PDH / PDL" in html
    assert "Full Day" in html
    assert "Asia (Tokyo)" in html
    assert "London Session" in html
    assert "New York Session" in html
    first_card = html[html.index('<article class="day-card'):html.index('</article>')]
    assert (
        first_card.index("Asia (Tokyo)")
        < first_card.index("London Session")
        < first_card.index("New York Session")
        < first_card.index("Full Day")
    )
    assert "18:00–03:00 ET" not in html
    # In Asia/Manila (November EST/GMT): Tokyo 8am-2pm, London 4:30pm-12:30am, NY 10:30pm-5am
    assert "8:00 AM–2:00 PM" in html
    assert "4:30 PM–12:30 AM" in html
    assert "10:30 PM–5:00 AM" in html
    assert "7:00 AM–6:00 AM" in html
    assert 'class="rangebar"' in html

    brief["hosted"] = True
    hosted_html = LVL.render(brief)
    assert 'href="index.html"' in hosted_html


def test_levels_page_session_status_badges_in_manila_time():
    from zoneinfo import ZoneInfo

    ph = ZoneInfo("Asia/Manila")
    today_row = {
        "date": "2026-11-27",
        "label": "Fri, Nov 27",
        "full_label": "Friday, Nov 27",
        "is_today": True,
        "open": 3650.0,
        "high": 3671.7,
        "high_t": "2026-11-27T14:50:00+00:00",
        "low": 3646.3,
        "low_t": "2026-11-27T16:15:00+00:00",
        "close": 3659.8,
        "chg_pct": 0.27,
        "range_pct": 0.70,
        "asia_h": None,
        "asia_h_t": "",
        "asia_l": None,
        "asia_l_t": "",
        "london_h": 3671.7,
        "london_h_t": "2026-11-27T14:50:00+00:00",
        "london_l": 3646.3,
        "london_l_t": "2026-11-27T16:15:00+00:00",
        "ny_h": 3671.7,
        "ny_h_t": "2026-11-27T14:50:00+00:00",
        "ny_l": 3646.3,
        "ny_l_t": "2026-11-27T16:15:00+00:00",
    }

    def _box_chunk(html_doc: str, start_lbl: str, end_lbl: str | None) -> str:
        s = html_doc.index(start_lbl)
        e = html_doc.index(end_lbl, s) if end_lbl else html_doc.index("</div>\n  <div class=\"rangebar-wrap\"", s)
        return html_doc[s:e]

    brief = {
        "tz": ph,
        "now": datetime(2026, 11, 28, 1, 15, tzinfo=ph),
        "symbols": {"gold": "GC=F", "us30": "YM=F", "us100": "NQ=F"},
        "snaps": {
            "gold": {
                "last": 3659.8,
                "today_levels": today_row,
                "levels_5d": [],
                "session_levels": {},
                "range_used": 0.5,
            }
        },
        "problems": [],
        "hosted": False,
    }
    html_night = LVL.render(brief)
    gold_night = html_night[html_night.index('id="lvl-gold"'):html_night.index('id="lvl-us30"')]
    assert "Closed" in _box_chunk(gold_night, "Asia (Tokyo)", "London Session")
    assert "Closed" in _box_chunk(gold_night, "London Session", "New York Session")
    assert "Forming" in _box_chunk(gold_night, "New York Session", "Full Day")
    assert "Forming" in _box_chunk(gold_night, "Full Day", None)

    brief["now"] = datetime(2026, 11, 27, 11, 0, tzinfo=ph)
    html_morning = LVL.render(brief)
    gold_morning = html_morning[html_morning.index('id="lvl-gold"'):html_morning.index('id="lvl-us30"')]
    assert "Forming" in _box_chunk(gold_morning, "Asia (Tokyo)", "London Session")
    assert "Upcoming" in _box_chunk(gold_morning, "London Session", "New York Session")
    assert "Upcoming" in _box_chunk(gold_morning, "New York Session", "Full Day")
    assert "Forming" in _box_chunk(gold_morning, "Full Day", None)

    brief["now"] = datetime(2026, 11, 27, 22, 0, tzinfo=ph)
    html_pre_ny = LVL.render(brief)
    gold_pre_ny = html_pre_ny[html_pre_ny.index('id="lvl-gold"'):html_pre_ny.index('id="lvl-us30"')]
    assert "Upcoming" in _box_chunk(gold_pre_ny, "New York Session", "Full Day")

    brief["now"] = datetime(2026, 11, 27, 22, 35, tzinfo=ph)
    html_ny_open = LVL.render(brief)
    gold_ny_open = html_ny_open[html_ny_open.index('id="lvl-gold"'):html_ny_open.index('id="lvl-us30"')]
    assert "Forming" in _box_chunk(gold_ny_open, "New York Session", "Full Day")

    assert LVL._fmt_window(LVL._session_bounds("2026-07-15", "Europe/London", 8, 30, 16, 30), ph) == "3:30 PM–11:30 PM"
    assert LVL._fmt_window(LVL._session_bounds("2026-11-27", "Europe/London", 8, 30, 16, 30), ph) == "4:30 PM–12:30 AM"
    assert LVL._fmt_window(LVL._session_bounds("2026-07-15", "America/New_York", 9, 30, 16, 0), ph) == "9:30 PM–4:00 AM"
    assert LVL._fmt_window(LVL._session_bounds("2026-11-27", "America/New_York", 9, 30, 16, 0), ph) == "10:30 PM–5:00 AM"


def test_session_levels_uses_ohlc_high_low_wicks():
    # Build two NY futures days where candle High/Low wicks extend beyond Close prices
    prev_start = pd.Timestamp("2026-11-22 18:00", tz="America/New_York").tz_convert("UTC")
    cur_start = pd.Timestamp("2026-11-23 18:00", tz="America/New_York").tz_convert("UTC")
    prev_idx = pd.date_range(prev_start, periods=276, freq="5min")
    cur_idx = pd.date_range(cur_start, periods=264, freq="5min")
    idx = prev_idx.append(cur_idx)

    closes = pd.Series([4100.0] * len(prev_idx) + [4200.0] * len(cur_idx), index=idx)
    opens = closes - 1.0
    highs = closes + 5.0
    lows = closes - 5.0

    # Inject sharper wicks in Asia/London/NY on prev day and cur day
    # prev London (2026-11-23 09:00 London = 04:00 EST) -> index offset inside prev_idx: 120 bars (10h after 18:00 ET = 04:00 ET)
    highs.iloc[120] = 4188.5
    lows.iloc[121] = 4011.25
    # prev NY after London close (2026-11-23 12:00 EST = 17:00 GMT = 18h after 18:00 ET) -> index 216
    highs.iloc[216] = 4199.0
    lows.iloc[217] = 4002.5
    # cur Asia (2026-11-24 10:00 JST = 20:00 EST prev day -> 2h after 18:00 ET = index 24 inside cur_idx)
    highs.iloc[len(prev_idx) + 24] = 4265.0
    lows.iloc[len(prev_idx) + 25] = 4175.0
    # cur NY (2026-11-24 10:00 EST = 16h after 18:00 ET -> index 192 inside cur_idx)
    highs.iloc[len(prev_idx) + 192] = 4295.0
    lows.iloc[len(prev_idx) + 193] = 4150.0

    closes.attrs["ohlc_open"] = opens
    closes.attrs["ohlc_high"] = highs
    closes.attrs["ohlc_low"] = lows

    sl = P.session_levels(closes)
    assert sl["pdh"] == 4199.0
    assert sl["pdl"] == 4002.5
    assert sl["pdc"] == 4100.0
    assert sl["prev_london_h"] == 4188.5
    assert sl["prev_london_l"] == 4011.25
    assert sl["prev_ny_h"] == 4199.0
    assert sl["prev_ny_l"] == 4002.5
    assert sl["asia_h"] == 4265.0
    assert sl["asia_l"] == 4175.0
    assert sl["ny_h"] == 4295.0
    assert sl["ny_l"] == 4150.0

    cur = P.current_day_levels(closes)
    assert cur is not None
    assert cur["open"] == 4199.0
    assert cur["high"] == 4295.0
    assert cur["low"] == 4150.0

    dl = P.daily_levels(closes, days=5)
    assert len(dl) == 1
    assert dl[0]["high"] == 4199.0
    assert dl[0]["low"] == 4002.5


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
