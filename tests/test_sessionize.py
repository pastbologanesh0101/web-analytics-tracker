"""Unit tests for the pure session-boundary derivation logic."""
from datetime import datetime, timedelta

from app.sessionize import derive_sessions


def _event(site_id, session_id, minutes_offset):
    return {
        "site_id": site_id,
        "session_id": session_id,
        "event_type": "pageview",
        "timestamp": datetime(2026, 1, 1, 10, 0, 0) + timedelta(minutes=minutes_offset),
    }


def test_events_within_timeout_stay_in_one_session():
    events = [
        _event("site-1", "sess-a", 0),
        _event("site-1", "sess-a", 5),
        _event("site-1", "sess-a", 29),  # still < 30 min gap from previous event
    ]
    derived = derive_sessions(events, timeout_minutes=30)
    ids = {e["derived_session_id"] for e in derived}
    assert len(ids) == 1


def test_gap_exceeding_timeout_splits_into_two_sessions():
    events = [
        _event("site-1", "sess-a", 0),
        _event("site-1", "sess-a", 10),
        # 45 minutes after the previous event -> exceeds the 30 min timeout
        _event("site-1", "sess-a", 55),
    ]
    derived = derive_sessions(events, timeout_minutes=30)
    ids_in_order = [e["derived_session_id"] for e in derived]
    assert ids_in_order[0] == ids_in_order[1]
    assert ids_in_order[2] != ids_in_order[1]
    assert len({e["derived_session_id"] for e in derived}) == 2


def test_different_sites_never_share_a_derived_session_even_with_same_session_id():
    events = [
        _event("site-1", "shared-id", 0),
        _event("site-2", "shared-id", 1),
    ]
    derived = derive_sessions(events, timeout_minutes=30)
    ids = {e["derived_session_id"] for e in derived}
    assert len(ids) == 2
