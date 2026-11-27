from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import main as M
from brief import dashboard as D
from brief.config import load_settings


def test_dashboard_renders_sparklines_filter_and_safety(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "DASHBOARD_FILE", tmp_path / "dashboard.html")
    monkeypatch.setattr(M, "HISTORY_PAGE_FILE", tmp_path / "history.html")
    settings = load_settings()
    brief, html = M.run_cycle(settings, demo=True, memory={})

    assert '<svg class="spark"' in html
    assert "<polyline" in html
    assert "bias trend:" in html
    assert 'data-hl="tagged"' in html
    assert 'sessionStorage.removeItem("briefScroll")' in html

    # Check FOMC at p > 80 renders .flip label, close events stagger, clamped badge,
    # negative age clamped to 0m ago, and javascript: link blocked
    tz = ZoneInfo("Asia/Manila")
    now = datetime(2026, 11, 25, 13, 0, tzinfo=timezone.utc)
    start = datetime(2026, 11, 25, 6, 0, tzinfo=tz).astimezone(timezone.utc)
    brief["tz"] = tz
    brief["now"] = now
    brief["night"] = {
        "start": start,
        "end": start + timedelta(hours=24),
        "title": "Your trading day, 6am to 6am",
        "sessions": [],
    }
    brief["releases"] = [
        {"time": start + timedelta(hours=14, minutes=30), "impact": "High", "headline": "CPI m/m",
         "status": "upcoming", "all_day": False, "lead_only": False, "others": [],
         "events": [{"title": "CPI m/m", "forecast": "0.3%", "previous": "0.2%"}]},
        {"time": start + timedelta(hours=16, minutes=0), "impact": "High", "headline": "ISM Services PMI",
         "status": "upcoming", "all_day": False, "lead_only": False, "others": [],
         "events": [{"title": "ISM Services PMI", "forecast": "52.0", "previous": "51.8"}]},
        {"time": start + timedelta(hours=20, minutes=0), "impact": "High", "headline": "FOMC Statement",
         "status": "upcoming", "all_day": False, "lead_only": False, "others": [],
         "events": [{"title": "FOMC Statement", "forecast": "", "previous": ""}]},
    ]
    brief["bias"]["gold"]["clamped"] = True
    brief["headlines"] = [
        {"title": "Future clock skew story", "source": "Test", "link": "javascript:alert(1)",
         "time": now + timedelta(minutes=5), "tags": []},
    ]
    rendered = D.render(brief)
    assert "FOMC Statement" in rendered
    assert "rel-label flip" in rendered
    assert "rel-label stagger" in rendered
    assert "lane tall" in rendered
    assert "(capped)" in rendered
    assert "0m ago" in rendered
    assert "javascript:alert" not in rendered
