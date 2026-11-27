from datetime import datetime, timedelta, timezone

from brief import news as N


def test_not_us_context_and_negation_traps():
    # Non-US without US context -> hawkish/dovish stripped
    assert "hawkish" not in N._tag("ECB stays hawkish as eurozone inflation cools")
    # Non-US WITH US context -> Fed hawkish preserved
    assert "hawkish" in N._tag("Fed stays hawkish as China tariffs lift US yields rise")
    assert "hawkish" in N._tag("Powell says Fed in no rush to cut despite China slowdown")

    # Negation traps
    tags_delay = N._tag("Fed delays rate cuts as inflation persists")
    assert "dovish" not in tags_delay and "hawkish" in tags_delay

    tags_hyph = N._tag("Traders trim rate-cut bets ahead of inflation report")
    assert "dovish" not in tags_hyph and "hawkish" in tags_hyph

    tags_rec = N._tag("US economy avoids recession as consumer spending holds")
    assert "dovish" not in tags_rec

    tags_deal = N._tag("US-China trade deal stalls ahead of summit")
    assert "risk-on" not in tags_deal

    tags_tariff = N._tag("US announces tariff pause on key imports")
    assert "risk-off" not in tags_tariff and "risk-on" in tags_tariff


def test_nasdaq_and_sp_tagging():
    assert "risk-off" in N._tag("Nasdaq tumbles 2% as tech selloff deepens")
    assert "risk-on" in N._tag("S&P rallies to record on strong earnings")


def test_near_duplicate_clustering_prefers_trusted(monkeypatch):
    now = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
    fake_items = [
        {
            "title": "Gold drops sharply as dollar gains ahead of CPI report",
            "source": "Random Blog",
            "link": "https://randomblog.example/1",
            "time": now - timedelta(minutes=10),
            "trusted": False,
        },
        {
            "title": "Gold drops sharply as dollar gains ahead of US CPI report",
            "source": "Reuters",
            "link": "https://reuters.com/1",
            "time": now - timedelta(minutes=15),
            "trusted": True,
        },
        {
            "title": "Malicious script test",
            "source": "Reuters",
            "link": "javascript:alert(1)",
            "time": now - timedelta(minutes=20),
            "trusted": True,
        },
    ]

    def fake_fetch(q, session):
        return fake_items if q == N.QUERIES[0] else []

    monkeypatch.setattr(N, "_fetch_query", fake_fetch)
    hls, probs = N.fetch_headlines(now=now)
    assert not probs
    titles = [h["title"] for h in hls]
    # Duplicate collapsed and trusted Reuters won over Random Blog
    assert sum("Gold drops" in t for t in titles) == 1
    gold_hl = next(h for h in hls if "Gold drops" in h["title"])
    assert gold_hl["source"] == "Reuters"


def test_recency_decay_in_tone():
    now = datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc)
    hls = [
        {"title": "Fresh hawk", "tags": ["hawkish"], "time": now - timedelta(minutes=30)},
        {"title": "Old dove", "tags": ["dovish"], "time": now - timedelta(hours=11)},
    ]
    res = N.tone(hls, now=now)
    assert res["rates"] > 0.1
    assert res["count"]["hawkish"] == 1 and res["count"]["dovish"] == 1
    # Backwards compatible when now=None
    res_flat = N.tone(hls)
    assert res_flat["rates"] == 0.0
