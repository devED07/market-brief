import json
from datetime import datetime, timedelta, timezone

from brief import geo as G


def _gdelt_row(a1: str, a2: str, root: str, goldstein: str, articles: str) -> str:
    cols = [""] * 35
    cols[G.COL_ACTOR1_COUNTRY] = a1
    cols[G.COL_ACTOR2_COUNTRY] = a2
    cols[G.COL_ROOT] = root
    cols[G.COL_GOLDSTEIN] = goldstein
    cols[G.COL_ARTICLES] = articles
    return "\t".join(cols)


def test_count_events_weighting_and_caps():
    raw = "\n".join([
        _gdelt_row("USA", "CHN", "19", "-10.0", "50"),  # material conflict capped at 20 -> 2*20=40 conflict, 20 total
        _gdelt_row("USA", "RUS", "17", "-2.0", "5"),    # coercion with mild Goldstein > -4.0 -> 0 conflict, 5 total
        _gdelt_row("USA", "IRN", "17", "-7.0", "4"),    # coercion with strong Goldstein <= -4.0 -> 4 conflict, 4 total
        _gdelt_row("USA", "USA", "19", "-10.0", "10"),  # domestic ignored
        _gdelt_row("USA", "GBR", "04", "3.0", "10"),    # cooperative -> 0 conflict, 10 total
    ])
    c, tot = G.count_events(raw)
    assert c == 44
    assert tot == 39


def test_incremental_loop_breaks_and_memoizes_404(tmp_path, monkeypatch):
    hist_file = tmp_path / "geo_history.json"
    monkeypatch.setattr(G, "HISTORY_FILE", hist_file)

    now = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
    # Pre-seed 22 days of history including `latest` slot (above 20-day backfill threshold)
    slots = {}
    for d in range(1, 23):
        day = now - timedelta(days=d)
        slots[G._stamp(day)] = [10, 100]
    latest = now.replace(minute=0, second=0, microsecond=0)
    slots[G._stamp(latest)] = [12, 100]
    hist_file.write_text(json.dumps({"v": G.SCHEMA_VERSION, "slots": slots}), encoding="utf-8")

    monkeypatch.setattr(G, "_latest_slot", lambda: latest)
    downloaded = []
    monkeypatch.setattr(G, "_download", lambda s: downloaded.append(s) or None)

    G.update_history(now)
    assert downloaded == []  # stopped immediately at `latest`, did not rescan 26h

    # Now advance `latest` by 30m where newest returns None (404) and 15m prior returns data
    new_latest = latest + timedelta(minutes=30)
    mid_slot = latest + timedelta(minutes=15)
    monkeypatch.setattr(G, "_latest_slot", lambda: new_latest)
    calls = []

    def fake_dl(s):
        calls.append(s)
        if s == new_latest:
            return None
        return (15, 100)

    monkeypatch.setattr(G, "_download", fake_dl)
    hist = G.update_history(now + timedelta(minutes=35))
    assert hist[G._stamp(new_latest)] == [0, 0]
    assert hist[G._stamp(mid_slot)] == [15, 100]

    # Next run with same `new_latest` must NOT re-download the 404 slot!
    calls.clear()
    G.update_history(now + timedelta(minutes=40))
    assert calls == []


def test_legacy_v1_schema_resets_cleanly(tmp_path, monkeypatch):
    hist_file = tmp_path / "geo_history.json"
    monkeypatch.setattr(G, "HISTORY_FILE", hist_file)
    hist_file.write_text(json.dumps({"20261120120000": [5, 50]}), encoding="utf-8")
    assert G._load_history() == {}
