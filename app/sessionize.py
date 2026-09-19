"""Session-boundary derivation.

A "session" is not a database row - it is derived from the raw event stream
at reporting time. Events sharing the same ``(site_id, session_id)`` belong
to the same session ONLY while consecutive events are within
``timeout_minutes`` of each other. If a client re-uses a ``session_id``
(e.g. the same browser tab, localStorage value not yet expired vs. a client
bug, or a long-lived id) after a gap larger than the timeout, that later
burst of events is treated as a brand new session for reporting purposes.

This mirrors how real web analytics tools (e.g. Google Analytics) define
"session" - a raw session/client identifier is NOT the same thing as an
analytics session.
"""
from collections import defaultdict
from datetime import timedelta

DEFAULT_TIMEOUT_MINUTES = 30


def derive_sessions(events, timeout_minutes=DEFAULT_TIMEOUT_MINUTES):
    """Assign a ``derived_session_id`` to each event.

    Parameters
    ----------
    events : list[dict]
        Each dict must contain at least ``site_id``, ``session_id`` and a
        ``timestamp`` that is a ``datetime.datetime`` (already parsed).
    timeout_minutes : int
        Inactivity gap (in minutes) after which a reused session_id starts a
        brand new derived session.

    Returns
    -------
    list[dict]
        Shallow copies of the input events, each with an added
        ``derived_session_id`` key, sorted back into overall timestamp
        order. The derived id is unique per (site_id, session_id, burst)
        so that reused ids after a long gap never collide with the earlier
        session.
    """
    timeout = timedelta(minutes=timeout_minutes)

    groups = defaultdict(list)
    for event in events:
        key = (event["site_id"], event["session_id"])
        groups[key].append(event)

    result = []
    for (site_id, session_id), group_events in groups.items():
        ordered = sorted(group_events, key=lambda e: e["timestamp"])
        burst = 0
        prev_ts = None
        derived_id = None
        for event in ordered:
            ts = event["timestamp"]
            if prev_ts is None or (ts - prev_ts) > timeout:
                burst += 1
                derived_id = f"{site_id}::{session_id}::{burst}"
            new_event = dict(event)
            new_event["derived_session_id"] = derived_id
            result.append(new_event)
            prev_ts = ts

    result.sort(key=lambda e: e["timestamp"])
    return result
