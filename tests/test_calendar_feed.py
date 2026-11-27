import json
import time
from datetime import datetime, timezone

from brief import calendar_feed as C


def test_usd_events_and_group_releases():
    rows = [
        {"title": "Core CPI m/m", "country": "USD", "date": "2026-11-12T08:30:00-05:00", "impact": "High", "forecast": "0.3%", "previous": "0.3%"},
        {"title": "CPI m/m", "country": "USD", "date": "2026-11-12T08:30:00-05:00", "impact": "High", "forecast": "0.3%", "previous": "0.2%"},
        {"title": "Unemployment Claims", "country": "USD", "date": "2026-11-12T08:30:00-05:00", "impact": "Medium", "forecast": "220K", "previous": "218K"},
        {"title": "Import Prices m/m", "country": "USD", "date": "2026-11-13T08:30:00-05:00", "impact": "Low", "forecast": "0.1%", "previous": "0.2%"},
        {"title": "Unrelated Low Event", "country": "USD", "date": "2026-11-13T10:00:00-05:00", "impact": "Low", "forecast": "", "previous": ""},
        {"title": "German CPI", "country": "EUR", "date": "2026-11-12T08:00:00+01:00", "impact": "High", "forecast": "0.2%", "previous": "0.1%"},
        {"title": "FOMC Press Conference", "country": "USD", "date": "2026-11-18T14:30:00-05:00", "impact": "High", "forecast": "", "previous": ""},
        {"title": "FOMC Statement", "country": "USD", "date": "2026-11-18T14:00:00-05:00", "impact": "High", "forecast": "", "previous": ""},
        {"title": "Presidential Election", "country": "USD", "date": "2026-11-03T08:00:00-05:00", "impact": "High", "forecast": "", "previous": ""},
    ]
    events = C.usd_events(rows)
    titles = [e["title"] for e in events]
    assert "German CPI" not in titles
    assert "Unrelated Low Event" not in titles
    assert "Import Prices m/m" in titles

    rels = C.group_releases(events)
    election = next(r for r in rels if "Election" in r["headline"])
    assert election["all_day"] is True

    cpi_grp = next(r for r in rels if "CPI" in r["headline"])
    assert cpi_grp["impact"] == "High"
    assert cpi_grp["window_min"] == 15
    assert cpi_grp["top_tier"] is True
    assert len(cpi_grp["events"]) == 3

    fomc_stmt = next(r for r in rels if r["headline"] == "FOMC Statement")
    assert fomc_stmt["window_min"] == 30
    fomc_pc = next(r for r in rels if r["headline"] == "FOMC Press Conference")
    assert fomc_pc["window_min"] == 45


def test_load_raw_uses_stale_cache_on_network_failure(tmp_path, monkeypatch):
    cache_file = tmp_path / "calendar_cache.json"
    monkeypatch.setattr(C, "CACHE_FILE", cache_file)
    old_rows = [{"title": "CPI m/m", "country": "USD"}]
    cache_file.write_text(json.dumps({"fetched_at": time.time() - 7200, "rows": old_rows}), encoding="utf-8")

    def boom():
        raise ConnectionError("offline")

    monkeypatch.setattr(C, "_download", boom)
    rows, fresh, note = C.load_raw()
    assert rows == old_rows
    assert fresh is False
    assert "ConnectionError" in note
