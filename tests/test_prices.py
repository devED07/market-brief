from datetime import datetime, timedelta, timezone

import pandas as pd

from brief import prices as P


def test_price_at_and_max_gap():
    t0 = datetime(2026, 11, 20, 13, 0, tzinfo=timezone.utc)
    idx = pd.date_range(t0, periods=12, freq="5min", tz="UTC")
    s = pd.Series([100.0 + i for i in range(12)], index=idx)

    # Bar ending at 13:30 has timestamp 13:25 (index 5 -> 105.0)
    assert P.price_at(s, t0 + timedelta(minutes=30)) == 105.0
    # Way after last bar (>20 min gap) returns None
    assert P.price_at(s, t0 + timedelta(minutes=120), max_gap_min=20) is None
    assert P.price_at(pd.Series(dtype=float), t0) is None


def test_snapshot_rejects_weekend_gaps_and_uses_5_trading_days():
    # Build 5 trading days (Mon-Fri Nov 16..20 2026, 10:00-16:00 NY) + Sunday reopen Nov 22 18:05..18:25 NY
    bars = []
    vals = []
    price = 100.0
    for day_offset in range(5):
        day_start = pd.Timestamp(f"2026-11-{16 + day_offset} 10:00", tz="America/New_York").tz_convert("UTC")
        day_idx = pd.date_range(day_start, periods=72, freq="5min")
        for ts in day_idx:
            bars.append(ts)
            price += 0.1
            vals.append(price)

    fri_close = vals[-1]
    sun_open = pd.Timestamp("2026-11-22 18:05", tz="America/New_York").tz_convert("UTC")
    for i in range(5):
        bars.append(sun_open + pd.Timedelta(minutes=5 * i))
        vals.append(fri_close + 2.0 + i * 0.1)

    series = pd.Series(vals, index=pd.DatetimeIndex(bars))
    now = (sun_open + pd.Timedelta(minutes=25)).to_pydatetime()
    snap = P.snapshot(series, now)

    # Only 20 min of bars exist after the 49h weekend gap: 30m and 4h must be None
    assert snap["chg_30m"] is None
    assert snap["chg_4h"] is None
    # 24h change looks back up to 72h so it compares Sunday open to Friday
    assert snap["chg_24h"] is not None and snap["chg_24h"] > 0
    # 5 trading days average is computed across the 5 distinct NY dates (not dropped to 3)
    assert snap["vs_5d"] is not None
    assert snap["stale_min"] == 5
    assert snap["cached"] is False
    assert snap["pdh"] is not None and snap["pdl"] is not None
    assert snap["pdh"] >= snap["pdl"]
    assert snap["range_used"] is not None


def test_snaps_cache_roundtrip_and_ttl(tmp_path, monkeypatch):
    cache_file = tmp_path / "snaps_cache.json"
    monkeypatch.setattr(P, "SNAPS_CACHE_FILE", cache_file)

    now = datetime(2026, 11, 24, 15, 0, tzinfo=timezone.utc)
    snaps = {
        "gold": {
            "last": 4200.0,
            "last_time": now - timedelta(minutes=30),
            "vs_5d": 0.5,
            "stale_min": 30,
            "cached": False,
            "chg_30m": 0.1,
            "chg_4h": 0.2,
            "chg_24h": 0.8,
        },
        "vix": {
            "last": 18.0,
            "last_time": now - timedelta(hours=10),
            "vs_5d": -1.0,
            "stale_min": 600,
            "cached": False,
            "chg_30m": 0.0,
            "chg_4h": 0.0,
            "chg_24h": 1.0,
        },
    }
    P.save_snaps_cache(snaps, now)

    weekday = P.load_snaps_cache(now + timedelta(minutes=15), max_age_min=120, weekend=False)
    assert "gold" in weekday
    assert weekday["gold"]["cached"] is True
    assert weekday["gold"]["stale_min"] == 45
    assert "vix" not in weekday  # expired (> 120m)

    wknd = P.load_snaps_cache(now + timedelta(hours=20), max_age_min=120, weekend=True)
    assert "gold" in wknd and "vix" in wknd


def test_fetch_oanda_series_and_fallback(monkeypatch):
    import json

    class _FakeResp:
        def __init__(self, body: dict):
            self._raw = json.dumps(body).encode("utf-8")

        def read(self) -> bytes:
            return self._raw

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    seen = {}

    def fake_opener(req, timeout=20):
        seen["url"] = req.full_url
        seen["auth"] = req.get_header("Authorization")
        return _FakeResp({
            "instrument": "XAU_USD",
            "candles": [
                {"time": "2026-11-27T01:00:00Z", "mid": {"o": "3650.0", "h": "3666.47", "l": "3648.0", "c": "3660.0"}},
                {"time": "2026-11-27T01:05:00Z", "mid": {"o": "3660.0", "h": "3662.0", "l": "3640.5", "c": "3655.0"}},
                {"time": "2026-11-27T01:10:00Z", "mid": {"o": "3655.0", "h": "3658.0", "l": "3651.0", "c": "3654.0"}},
            ],
        })

    s = P.fetch_oanda_series("XAU_USD", "tok-123", env="practice", opener=fake_opener)
    assert "https://api-fxpractice.oanda.com/v3/instruments/XAU_USD/candles" in seen["url"]
    assert seen["auth"] == "Bearer tok-123"
    assert s.attrs["source"] == "oanda"
    assert float(s.attrs["ohlc_high"].max()) == 3666.47
    assert float(s.attrs["ohlc_low"].min()) == 3640.5
    assert float(s.attrs["ohlc_open"].iloc[0]) == 3650.0

    now = datetime(2026, 11, 27, 1, 15, tzinfo=timezone.utc)
    snap = P.snapshot(s, now)
    assert snap["source"] == "oanda"
    assert snap["last"] == 3654.0

    # fetch_all uses OANDA when available and falls back to Yahoo when OANDA raises
    def fake_oanda(instrument, api_key, env="practice", count=3000, opener=None):
        if instrument == "US30_USD":
            raise RuntimeError("boom")
        return s

    fallback_idx = pd.date_range("2026-11-27T01:00:00Z", periods=3, freq="5min", tz="UTC")
    fallback_s = pd.Series([50500.0, 50550.0, 50600.0], index=fallback_idx)
    fallback_s.attrs["source"] = "yahoo"
    monkeypatch.setattr(P, "fetch_oanda_series", fake_oanda)
    monkeypatch.setattr(P, "fetch_series", lambda sym: fallback_s)

    series, snaps, problems = P.fetch_all(
        {"gold": "GC=F", "us30": "YM=F"},
        now=now,
        oanda_key="tok-123",
        oanda_env="practice",
        oanda_symbols={"gold": "XAU_USD", "us30": "US30_USD"},
    )
    assert snaps["gold"]["source"] == "oanda"
    assert snaps["us30"]["source"] == "yahoo"
    assert "falling back to YM=F" in problems[0]
    assert len(series) == 2
