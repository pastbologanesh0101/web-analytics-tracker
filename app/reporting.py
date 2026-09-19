"""Reporting endpoints and the simple HTML dashboard.

All reports are computed on read: raw events are loaded (optionally scoped
to a ``site_id`` query parameter), passed through
``sessionize.derive_sessions`` to establish real session boundaries, and
then aggregated in Python. This keeps the write path (``/collect``) trivial
and keeps all "what counts as a session" logic in one place.
"""
import json
from collections import Counter, defaultdict
from datetime import datetime

from flask import Blueprint, current_app, jsonify, render_template, request

from .db import get_db
from .sessionize import derive_sessions

bp = Blueprint("reporting", __name__)


def _load_events(site_id=None):
    db = get_db()
    if site_id:
        rows = db.execute(
            "SELECT * FROM raw_events WHERE site_id = ? ORDER BY timestamp",
            (site_id,),
        ).fetchall()
    else:
        rows = db.execute("SELECT * FROM raw_events ORDER BY timestamp").fetchall()

    events = []
    for row in rows:
        events.append(
            {
                "id": row["id"],
                "site_id": row["site_id"],
                "session_id": row["session_id"],
                "event_type": row["event_type"],
                "event_name": row["event_name"],
                "page_url": row["page_url"],
                "referrer": row["referrer"],
                "user_agent": row["user_agent"],
                "timestamp": datetime.fromisoformat(row["timestamp"]),
                "properties": json.loads(row["properties"]) if row["properties"] else None,
            }
        )
    return events


def get_sessionized_events(site_id=None):
    timeout_minutes = current_app.config.get("SESSION_TIMEOUT_MINUTES", 30)
    events = _load_events(site_id)
    return derive_sessions(events, timeout_minutes=timeout_minutes)


def compute_daily_pageviews(events):
    buckets = defaultdict(int)
    for event in events:
        if event["event_type"] == "pageview":
            day = event["timestamp"].strftime("%Y-%m-%d")
            buckets[day] += 1
    return dict(sorted(buckets.items()))


def compute_daily_sessions(events):
    """Bucket sessions by the day their FIRST event occurred."""
    first_seen = {}
    for event in events:
        sid = event["derived_session_id"]
        ts = event["timestamp"]
        if sid not in first_seen or ts < first_seen[sid]:
            first_seen[sid] = ts
    buckets = defaultdict(int)
    for ts in first_seen.values():
        buckets[ts.strftime("%Y-%m-%d")] += 1
    return dict(sorted(buckets.items()))


def compute_top_pages(events, limit=10):
    counts = Counter(
        event["page_url"]
        for event in events
        if event["event_type"] == "pageview" and event["page_url"]
    )
    return [{"page_url": url, "pageviews": count} for url, count in counts.most_common(limit)]


def compute_top_referrers(events, limit=10):
    """Rank referrers by number of SESSIONS they initiated (the referrer of
    each session's first pageview), not raw pageview count, so a single
    long session doesn't drown out a referrer that brought many visitors."""
    session_first_pageview = {}
    for event in events:
        if event["event_type"] != "pageview":
            continue
        sid = event["derived_session_id"]
        if sid not in session_first_pageview or event["timestamp"] < session_first_pageview[sid]["timestamp"]:
            session_first_pageview[sid] = event

    referrers = [
        (event["referrer"] or "(direct)") for event in session_first_pageview.values()
    ]
    counts = Counter(referrers)
    return [{"referrer": ref, "sessions": count} for ref, count in counts.most_common(limit)]


def compute_bounce_rate(events):
    """Bounce rate = sessions with exactly one pageview / total sessions."""
    pageview_counts = defaultdict(int)
    all_sessions = set()
    for event in events:
        sid = event["derived_session_id"]
        all_sessions.add(sid)
        if event["event_type"] == "pageview":
            pageview_counts[sid] += 1

    total_sessions = len(all_sessions)
    bounced = sum(1 for sid in all_sessions if pageview_counts.get(sid, 0) == 1)
    rate = (bounced / total_sessions) if total_sessions else 0.0
    return {
        "total_sessions": total_sessions,
        "bounced_sessions": bounced,
        "bounce_rate": round(rate, 4),
    }


def compute_custom_event_breakdown(events):
    counts = Counter(
        event["event_name"]
        for event in events
        if event["event_type"] == "custom" and event["event_name"]
    )
    return dict(counts)


@bp.route("/report/pageviews")
def report_pageviews():
    events = get_sessionized_events(request.args.get("site_id"))
    return jsonify(compute_daily_pageviews(events))


@bp.route("/report/sessions")
def report_sessions():
    events = get_sessionized_events(request.args.get("site_id"))
    return jsonify(compute_daily_sessions(events))


@bp.route("/report/top-pages")
def report_top_pages():
    events = get_sessionized_events(request.args.get("site_id"))
    limit = int(request.args.get("limit", 10))
    return jsonify(compute_top_pages(events, limit=limit))


@bp.route("/report/top-referrers")
def report_top_referrers():
    events = get_sessionized_events(request.args.get("site_id"))
    limit = int(request.args.get("limit", 10))
    return jsonify(compute_top_referrers(events, limit=limit))


@bp.route("/report/bounce-rate")
def report_bounce_rate():
    events = get_sessionized_events(request.args.get("site_id"))
    return jsonify(compute_bounce_rate(events))


@bp.route("/report/events")
def report_events():
    events = get_sessionized_events(request.args.get("site_id"))
    return jsonify(compute_custom_event_breakdown(events))


@bp.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")
