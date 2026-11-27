from datetime import datetime, timedelta, timezone

from brief import leadup as L


def test_co_release_non_contamination_and_fred_override():
    now = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
    nfp_t = datetime(2026, 11, 14, 13, 30, tzinfo=timezone.utc)
    thu_t = datetime(2026, 11, 12, 13, 30, tzinfo=timezone.utc)

    nfp_rel = {
        "time": nfp_t, "status": "upcoming", "all_day": False,
        "headline": "Non-Farm Employment Change",
        "events": [{"title": "Non-Farm Employment Change"}],
    }
    # Without FRED actuals, CPI + Unemployment Claims must NOT pass CPI's hawk reaction to Claims
    log_no_fred = [{
        "time": thu_t,
        "headline": "Core CPI m/m",
        "titles": ["Core CPI m/m", "CPI m/m", "Unemployment Claims"],
        "hawk": 1.8,
        "verdict": "Hawkish surprise",
        "data": {},
    }]
    reads = L.build([nfp_rel], log_no_fred, now)
    assert len(reads) == 1
    assert reads[0]["scored"] == []

    # With FRED actuals for Unemployment Claims, it IS scored cleanly
    log_with_fred = [{
        "time": thu_t,
        "headline": "Core CPI m/m",
        "titles": ["Core CPI m/m", "CPI m/m", "Unemployment Claims"],
        "hawk": 1.8,
        "verdict": "Hawkish surprise",
        "data": {"Unemployment Claims": {"z": -0.8, "text": "230K vs 220K forecast"}},
    }]
    reads2 = L.build([nfp_rel], log_with_fred, now)
    assert len(reads2[0]["scored"]) == 1
    assert reads2[0]["scored"][0]["hawk"] == -0.8


def test_weekly_claims_deduplication_and_cpi_lookback():
    now = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
    nfp_t = datetime(2026, 11, 14, 13, 30, tzinfo=timezone.utc)
    nfp_rel = {
        "time": nfp_t, "status": "upcoming", "all_day": False,
        "headline": "Non-Farm Employment Change",
        "events": [{"title": "Non-Farm Employment Change"}],
    }
    log = [
        {"time": nfp_t - timedelta(days=9), "headline": "Unemployment Claims", "titles": ["Unemployment Claims"], "hawk": 1.0, "verdict": "Hawkish", "data": {}},
        {"time": nfp_t - timedelta(days=2), "headline": "Unemployment Claims", "titles": ["Unemployment Claims"], "hawk": 0.6, "verdict": "Leaned hawkish", "data": {}},
    ]
    read = L.build([nfp_rel], log, now)[0]
    assert len(read["scored"]) == 1
    assert "2 prints" in read["scored"][0]["text"]
    assert abs(read["scored"][0]["hawk"] - 0.8) < 1e-6
    assert read["confidence"] == "Low confidence"  # not inflated to Moderate by same weekly series

    # CPI 18-day lookback ignores a 22-day-old PPI
    cpi_t = datetime(2026, 11, 14, 13, 30, tzinfo=timezone.utc)
    cpi_rel = {
        "time": cpi_t, "status": "upcoming", "all_day": False,
        "headline": "CPI m/m", "events": [{"title": "CPI m/m"}],
    }
    old_ppi = [{"time": cpi_t - timedelta(days=22), "headline": "PPI m/m", "titles": ["PPI m/m"], "hawk": 1.0, "data": {}}]
    assert L.build([cpi_rel], old_ppi, now)[0]["scored"] == []


def test_pce_confidence_and_update_log_merge(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "LOG_FILE", tmp_path / "release_log.json")
    now = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 11, 18, 13, 30, tzinfo=timezone.utc)

    # First run had hawk reaction from Yahoo
    L.update_log([{
        "time": t1, "status": "done", "headline": "CPI m/m",
        "events": [{"title": "CPI m/m"}], "hawk": 1.2, "verdict": "Hawkish surprise",
        "data": {}, "weight": 1.5, "impact": "High", "lead_only": False,
    }], now, persist=True)

    # Second run has FRED actuals but Yahoo gap (hawk=None) -> preserves prior hawk!
    rows = L.update_log([{
        "time": t1, "status": "done", "headline": "CPI m/m",
        "events": [{"title": "CPI m/m"}], "hawk": None, "verdict": "No price data",
        "data": {"CPI m/m": {"z": 1.0, "text": "0.4% vs 0.3% forecast"}},
        "weight": 1.5, "impact": "High", "lead_only": False,
    }], now, persist=True)

    assert rows[0]["hawk"] == 1.2
    assert rows[0]["weight"] == 1.5
    assert "CPI m/m" in rows[0]["data"]

    pce_rel = {
        "time": now + timedelta(days=2), "status": "upcoming", "all_day": False,
        "headline": "Core PCE Price Index m/m",
        "events": [{"title": "Core PCE Price Index m/m"}],
    }
    read = L.build([pce_rel], rows, now)[0]
    assert "Mostly priced in" in read["confidence"]
    line = L.one_line(read)
    assert "CPI/PPI" in line
