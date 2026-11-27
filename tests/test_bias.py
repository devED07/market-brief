from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from brief import bias as B


ZERO_TONE = {
    "rates": 0.0,
    "risk": 0.0,
    "count": {"hawkish": 0, "dovish": 0, "risk-off": 0, "risk-on": 0, "geopolitics": 0, "de-escalation": 0},
}


def test_data_score_carries_friday_release_across_weekend_via_log():
    fri_nfp = datetime(2026, 11, 6, 13, 30, tzinfo=timezone.utc)
    mon_morning = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)  # ~70.5h later

    log = [{
        "time": fri_nfp,
        "headline": "Non-Farm Employment Change",
        "titles": ["Non-Farm Employment Change"],
        "hawk": 1.5,
        "verdict": "Hawkish surprise",
        "weight": 1.5,
        "lead_only": False,
    }]

    # Weekly calendar rolled over so `releases` is empty
    score, detail = B.data_score([], mon_morning, log=log)
    assert score is not None and score > 1.0
    assert "1 release scored" in detail
    assert "NFP" in detail


def test_flight_to_safety_dampens_bullish_yields_for_equities():
    now = datetime(2026, 11, 24, 15, 0, tzinfo=timezone.utc)
    snaps = {
        "gold": {"last": 4200.0, "chg_24h": 0.8, "chg_4h": 0.3, "vs_5d": 0.5, "stale_min": 10},
        "us30": {"last": 47000.0, "chg_24h": -1.2, "chg_4h": -0.6, "vs_5d": -1.0, "stale_min": 10},
        "us100": {"last": 25000.0, "chg_24h": -1.8, "chg_4h": -0.9, "vs_5d": -1.5, "stale_min": 10},
        "dollar": {"last": 100.0, "chg_24h": 0.0, "stale_min": 10},
        "treasury_10y": {"last": 112.0, "chg_24h": 0.45, "stale_min": 10},  # yields falling sharply
        "vix": {"last": 26.0, "chg_24h": 15.0, "stale_min": 10},
    }
    res = B.build([], snaps, ZERO_TONE, now)
    u_dy = next(d for d in res["us30"]["drivers"] if d["name"] == "Dollar and yields")
    n_dy = next(d for d in res["us100"]["drivers"] if d["name"] == "Dollar and yields")
    assert u_dy["points"] == 0.0
    assert n_dy["points"] == 0.0
    assert "flight to safety" in u_dy["detail"].lower()


def test_gold_sell_everything_checks_us100_too():
    snaps = {
        "gold": {"chg_24h": -0.9},
        "us100": {"chg_24h": -1.5},  # us30 absent, us100 down
    }
    pts, detail = B.gold_risk(1.0, "VIX 25.0", snaps)
    assert pts == 0.0
    assert "selling everything" in detail


def test_stale_vix_halves_change_component_when_market_open():
    snaps = {"vix": {"last": 18.0, "chg_24h": 10.0, "stale_min": 400}}
    s_open, d_open = B.risk_score(snaps, market_open=True)
    s_closed, d_closed = B.risk_score(snaps, market_open=False)
    assert abs(s_open - 0.5) < 1e-6
    assert abs(s_closed - 1.0) < 1e-6
    assert "stale 6h" in d_open
    assert "stale" not in d_closed


def test_market_status_cme_holidays():
    ny = ZoneInfo("America/New_York")
    gf = datetime(2026, 4, 3, 10, 0, tzinfo=ny).astimezone(timezone.utc)  # Good Friday
    st_gf = B.market_status(gf, ny)
    assert st_gf["open"] is False
    assert st_gf["reason"] == "holiday"
    assert st_gf["holiday_name"] == "Good Friday"
    assert st_gf["reopen"].weekday() == 6  # Sunday 6pm NY

    xmas = datetime(2026, 12, 25, 11, 0, tzinfo=ny).astimezone(timezone.utc)
    assert B.market_status(xmas, ny)["holiday_name"] == "Christmas Day"

    nyd = datetime(2026, 1, 1, 11, 0, tzinfo=ny).astimezone(timezone.utc)
    assert B.market_status(nyd, ny)["holiday_name"] == "New Year's Day"

    # Observed Christmas (Dec 25 2027 is Saturday -> observed Friday Dec 24)
    obs_xmas = datetime(2027, 12, 24, 11, 0, tzinfo=ny).astimezone(timezone.utc)
    assert B.market_status(obs_xmas, ny)["holiday_name"] == "Christmas Day"

    # Black Friday 2026 (Nov 27 2026): open at 10am, early close at 2pm
    bf_open = datetime(2026, 11, 27, 10, 0, tzinfo=ny).astimezone(timezone.utc)
    assert B.market_status(bf_open, ny)["open"] is True
    bf_closed = datetime(2026, 11, 27, 14, 0, tzinfo=ny).astimezone(timezone.utc)
    st_bf = B.market_status(bf_closed, ny)
    assert st_bf["open"] is False
    assert st_bf["reason"] == "early close"
    assert st_bf["holiday_name"] == "Day after Thanksgiving"


def test_sessions_for_night_wraps_in_ny_and_build_exposes_clamped():
    ny = ZoneInfo("America/New_York")
    now = datetime(2026, 11, 19, 15, 0, tzinfo=timezone.utc)
    night = B.sessions_for_night(now, ny)
    lon = next(s for s in night["sessions"] if s["name"] == "London")
    # London 3:00-11:30 ET spans the 6am ET boundary -> 2 segments
    assert len(lon["segments"]) == 2

    # Extreme drivers clamp to [-10, +10] while exposing raw_score and geo
    snaps = {
        "gold": {"last": 4200.0, "chg_24h": 4.0, "chg_4h": 2.0, "vs_5d": 4.0, "stale_min": 5},
        "us30": {"last": 47000.0, "chg_24h": 2.0, "chg_4h": 1.0, "vs_5d": 2.0, "stale_min": 5},
        "us100": {"last": 25000.0, "chg_24h": 2.0, "chg_4h": 1.0, "vs_5d": 2.0, "stale_min": 5},
        "dollar": {"last": 98.0, "chg_24h": -2.0, "stale_min": 5},
        "treasury_10y": {"last": 114.0, "chg_24h": 1.5, "stale_min": 5},
        "vix": {"last": 28.0, "chg_24h": 20.0, "stale_min": 5},
    }
    rel = [{
        "time": now - timedelta(hours=2), "headline": "CPI m/m", "status": "done",
        "hawk": -2.0, "verdict": "Dovish surprise", "weight": 1.5, "lead_only": False,
    }]
    tone = {"rates": -1.0, "risk": 1.0, "count": {"hawkish": 0, "dovish": 5, "risk-off": 5, "risk-on": 0, "geopolitics": 0, "de-escalation": 0}}
    out = B.build(rel, snaps, tone, now, geo=(1.5, "high"))
    assert out["gold"]["score"] == 10.0
    assert out["gold"]["raw_score"] > 10.0
    assert out["gold"]["clamped"] is True
    assert out["components"]["geo"] == 1.5
