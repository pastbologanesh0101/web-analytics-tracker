"""Tests for the ingestion endpoints: POST /collect and GET /collect."""
from app.db import get_db


def _row_count(app):
    with app.app_context():
        return get_db().execute("SELECT COUNT(*) AS c FROM raw_events").fetchone()["c"]


def test_post_collect_valid_event_is_stored_correctly(app, client):
    payload = {
        "site_id": "site-1",
        "session_id": "sess-abc",
        "event_type": "pageview",
        "page_url": "https://example.com/",
        "referrer": "https://google.com",
        "timestamp": "2026-01-01T10:00:00",
    }
    resp = client.post("/collect", json=payload)
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}

    with app.app_context():
        row = get_db().execute("SELECT * FROM raw_events").fetchone()
    assert row["site_id"] == "site-1"
    assert row["session_id"] == "sess-abc"
    assert row["event_type"] == "pageview"
    assert row["page_url"] == "https://example.com/"
    assert row["referrer"] == "https://google.com"
    assert row["timestamp"].startswith("2026-01-01T10:00:00")
    assert _row_count(app) == 1


def test_post_collect_missing_site_id_rejected_with_400(app, client):
    payload = {
        "session_id": "sess-abc",
        "timestamp": "2026-01-01T10:00:00",
    }
    resp = client.post("/collect", json=payload)
    assert resp.status_code == 400
    body = resp.get_json()
    assert "error" in body
    assert "site_id" in body["error"]
    assert _row_count(app) == 0


def test_post_collect_invalid_timestamp_rejected_with_400(app, client):
    payload = {
        "site_id": "site-1",
        "session_id": "sess-abc",
        "timestamp": "not-a-real-timestamp",
    }
    resp = client.post("/collect", json=payload)
    assert resp.status_code == 400
    body = resp.get_json()
    assert "error" in body
    assert "timestamp" in body["error"]
    assert _row_count(app) == 0


def test_post_collect_non_json_body_rejected_with_400(app, client):
    resp = client.post("/collect", data="not json", content_type="text/plain")
    assert resp.status_code == 400
    assert "error" in resp.get_json()
    assert _row_count(app) == 0


def test_get_collect_pixel_always_returns_200_even_with_missing_fields(app, client):
    # No query params at all - the classic "everything is wrong" case.
    resp = client.get("/collect")
    assert resp.status_code == 200
    assert resp.mimetype == "image/gif"
    assert len(resp.data) > 0
    # The page must never break, but garbage must not be written either.
    assert _row_count(app) == 0


def test_get_collect_pixel_stores_a_valid_event(app, client):
    resp = client.get(
        "/collect",
        query_string={
            "site_id": "site-1",
            "session_id": "sess-xyz",
            "page_url": "https://example.com/pricing",
            "timestamp": "2026-01-02T12:00:00",
        },
    )
    assert resp.status_code == 200
    assert resp.mimetype == "image/gif"
    assert _row_count(app) == 1
    with app.app_context():
        row = get_db().execute("SELECT * FROM raw_events").fetchone()
    assert row["site_id"] == "site-1"
    assert row["page_url"] == "https://example.com/pricing"


def test_get_collect_pixel_with_bad_timestamp_does_not_corrupt_storage(app, client):
    resp = client.get(
        "/collect",
        query_string={
            "site_id": "site-1",
            "session_id": "sess-xyz",
            "timestamp": "banana",
        },
    )
    # Still a happy 200/GIF response for the browser...
    assert resp.status_code == 200
    assert resp.mimetype == "image/gif"
    # ...but nothing bad gets persisted.
    assert _row_count(app) == 0


def test_track_js_is_served_as_javascript(client):
    resp = client.get("/track.js")
    assert resp.status_code == 200
    assert "javascript" in resp.mimetype
    assert "sendBeacon" in resp.get_data(as_text=True)
