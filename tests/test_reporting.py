"""Tests for the reporting endpoints, exercised through the Flask test client."""


def _post(client, **overrides):
    payload = {
        "site_id": "site-1",
        "session_id": "sess-1",
        "event_type": "pageview",
        "page_url": "https://example.com/",
        "referrer": None,
        "timestamp": "2026-01-01T10:00:00",
    }
    payload.update(overrides)
    resp = client.post("/collect", json=payload)
    assert resp.status_code == 200
    return resp


def test_daily_pageview_bucketing_is_correct(client):
    # 2 pageviews on Jan 1, 1 pageview on Jan 2.
    _post(client, session_id="s1", timestamp="2026-01-01T09:00:00")
    _post(client, session_id="s1", timestamp="2026-01-01T09:15:00")
    _post(client, session_id="s2", timestamp="2026-01-02T08:00:00")

    resp = client.get("/report/pageviews")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data == {"2026-01-01": 2, "2026-01-02": 1}


def test_top_pages_ranking_is_correct(client):
    _post(client, page_url="/a", session_id="s1", timestamp="2026-01-01T09:00:00")
    _post(client, page_url="/a", session_id="s2", timestamp="2026-01-01T09:05:00")
    _post(client, page_url="/a", session_id="s3", timestamp="2026-01-01T09:10:00")
    _post(client, page_url="/b", session_id="s4", timestamp="2026-01-01T09:15:00")
    _post(client, page_url="/b", session_id="s5", timestamp="2026-01-01T09:20:00")
    _post(client, page_url="/c", session_id="s6", timestamp="2026-01-01T09:25:00")

    resp = client.get("/report/top-pages")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data[0] == {"page_url": "/a", "pageviews": 3}
    assert data[1] == {"page_url": "/b", "pageviews": 2}
    assert data[2] == {"page_url": "/c", "pageviews": 1}


def test_top_referrers_ranking_is_correct(client):
    # 3 sessions arrive from google, 1 from twitter, 1 with no referrer (direct).
    _post(client, session_id="s1", referrer="https://google.com", timestamp="2026-01-01T09:00:00")
    _post(client, session_id="s2", referrer="https://google.com", timestamp="2026-01-01T09:05:00")
    _post(client, session_id="s3", referrer="https://google.com", timestamp="2026-01-01T09:10:00")
    _post(client, session_id="s4", referrer="https://twitter.com", timestamp="2026-01-01T09:15:00")
    _post(client, session_id="s5", referrer=None, timestamp="2026-01-01T09:20:00")

    resp = client.get("/report/top-referrers")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data[0] == {"referrer": "https://google.com", "sessions": 3}
    assert data[1] == {"referrer": "https://twitter.com", "sessions": 1}
    assert {"referrer": "(direct)", "sessions": 1} in data


def test_bounce_rate_is_computed_correctly(client):
    # Session s1: single pageview -> bounce.
    _post(client, session_id="s1", timestamp="2026-01-01T09:00:00")
    # Session s2: single pageview -> bounce.
    _post(client, session_id="s2", timestamp="2026-01-01T09:05:00")
    # Session s3: two pageviews -> NOT a bounce.
    _post(client, session_id="s3", timestamp="2026-01-01T09:10:00")
    _post(client, session_id="s3", timestamp="2026-01-01T09:12:00")

    resp = client.get("/report/bounce-rate")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_sessions"] == 3
    assert data["bounced_sessions"] == 2
    assert data["bounce_rate"] == round(2 / 3, 4)


def test_bounce_rate_reflects_session_boundary_split(client):
    # Same raw session_id, but the second pageview happens 45 minutes later,
    # i.e. past the 30-minute timeout, so it must be counted as its OWN new
    # session (also a bounce) rather than merged into the first one.
    _post(client, session_id="reused", timestamp="2026-01-01T09:00:00")
    _post(client, session_id="reused", timestamp="2026-01-01T09:45:00")

    resp = client.get("/report/bounce-rate")
    data = resp.get_json()
    assert data["total_sessions"] == 2
    assert data["bounced_sessions"] == 2
    assert data["bounce_rate"] == 1.0


def test_custom_event_breakdown_counts_correctly(client):
    _post(client, session_id="s1", event_type="custom", event_name="signup", timestamp="2026-01-01T09:00:00")
    _post(client, session_id="s2", event_type="custom", event_name="signup", timestamp="2026-01-01T09:05:00")
    _post(client, session_id="s3", event_type="custom", event_name="purchase", timestamp="2026-01-01T09:10:00")
    # A pageview should not show up in the custom-event breakdown at all.
    _post(client, session_id="s4", event_type="pageview", timestamp="2026-01-01T09:15:00")

    resp = client.get("/report/events")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data == {"signup": 2, "purchase": 1}


def test_reports_can_be_scoped_by_site_id(client):
    _post(client, site_id="site-a", session_id="s1", page_url="/a", timestamp="2026-01-01T09:00:00")
    _post(client, site_id="site-b", session_id="s2", page_url="/b", timestamp="2026-01-01T09:00:00")

    resp = client.get("/report/top-pages", query_string={"site_id": "site-a"})
    data = resp.get_json()
    assert data == [{"page_url": "/a", "pageviews": 1}]


def test_dashboard_route_renders_html(client):
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert b"Web Analytics Tracker" in resp.data
