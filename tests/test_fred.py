from datetime import date, datetime, timezone

import requests

from brief import fred as F


def test_unit_aware_surprise_and_fmt_like():
    # 980K vs 1.05M (1050K) -> -70K surprise with sigma=12K -> clamped to -2.0 * sign(-1) = +2.0 (for ICSA)
    # Wait: for NFP sign=+1: 980K vs 1.05M -> -70 / 60 = -1.166667
    z = F.surprise("980K", "1.05M", sigma=60, sign=1, unit="K")
    assert z is not None and abs(z - (-70 / 60)) < 1e-4

    assert F.fmt_like(1050.0, "1.0M", default_unit="K") == "1.1M"
    assert F.fmt_like(58.0, "42K", default_unit="K") == "58K"
    assert F.fmt_like(0.32, "0.3%", default_unit="%") == "0.3%"


def test_parse_fred_ts_variants():
    assert F._parse_fred_ts("2026-11-27 08:30:00-06").utcoffset().total_seconds() == -6 * 3600
    assert F._parse_fred_ts("2026-11-27 08:30:00-0500").utcoffset().total_seconds() == -5 * 3600
    assert F._parse_fred_ts("2026-11-27 13:30:00+00:00").utcoffset().total_seconds() == 0
    assert F._parse_fred_ts("2026-11-27T13:30:00Z").tzinfo == timezone.utc


def test_headline_number_period_matching_and_zero_guard():
    # Monthly CPI series: Oct 1 obs released Nov 12; Dec 10 release has Nov 1 obs
    obs = [
        (date(2026, 9, 1), 100.0),
        (date(2026, 10, 1), 100.3),
        (date(2026, 11, 1), 100.9),
    ]
    nov_rel = datetime(2026, 11, 12, 13, 30, tzinfo=timezone.utc)
    val = F._headline_number(obs, "pct_mom", rel_time=nov_rel, freq="monthly")
    assert val is not None and abs(val - 0.3) < 1e-6  # picks Oct vs Sep, NOT Nov vs Oct!

    # Zero-division guard
    assert F._headline_number([(date(2026, 9, 1), 0.0), (date(2026, 10, 1), 100.0)], "pct_mom") is None


def test_attach_isolates_per_series_400_from_401_auth(tmp_path, monkeypatch):
    monkeypatch.setattr(F, "ACTUALS_FILE", tmp_path / "actuals.json")

    class FakeResp:
        def __init__(self, code, msg=""):
            self.status_code = code
            self._msg = msg
            self.text = msg
        def json(self):
            return {"error_message": self._msg}

    class FakeFred:
        def last_updated(self, series):
            if series == "BADSERIES":
                raise requests.HTTPError(response=FakeResp(400, "Series does not exist"))
            return datetime(2026, 11, 20, 14, 0, tzinfo=timezone.utc)
        def observations(self, series):
            return [(date(2026, 9, 1), 100.0), (date(2026, 10, 1), 100.4)]

    monkeypatch.setitem(F.SERIES, "broken indicator", ("BADSERIES", "level", 1, 1.0, 1, "%"))
    now = datetime(2026, 11, 20, 15, 0, tzinfo=timezone.utc)
    rel_t = datetime(2026, 11, 20, 13, 30, tzinfo=timezone.utc)
    releases = [{
        "time": rel_t, "all_day": False,
        "events": [
            {"title": "Broken Indicator", "forecast": "1.0%", "previous": "1.0%"},
            {"title": "CPI m/m", "forecast": "0.3%", "previous": "0.2%"},
        ],
    }]
    problem = F.attach(releases, now, "dummy", persist=True, fred=FakeFred())
    assert "BADSERIES" in problem
    # CPI still resolved despite BADSERIES 400 error!
    assert releases[0]["events"][1]["actual"] == "0.4%"
    assert "CPI m/m" in releases[0]["data"]

    # Now verify 401 aborts cleanly
    class BadKeyFred:
        def last_updated(self, series):
            raise requests.HTTPError(response=FakeResp(401, "Bad API key"))

    releases2 = [{"time": rel_t, "all_day": False, "events": [{"title": "CPI m/m", "forecast": "0.3%", "previous": "0.2%"}]}]
    assert F.attach(releases2, now, "bad", persist=False, fred=BadKeyFred()) == "FRED rejected the API key"
