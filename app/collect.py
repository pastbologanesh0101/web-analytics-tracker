"""Ingestion endpoints: /track.js and /collect.

Validation contract (see README for the full write-up)
--------------------------------------------------------
* ``POST /collect`` expects a JSON body. A malformed body (not JSON,
  missing ``site_id``, missing/invalid ``timestamp``, missing
  ``session_id``, or an unknown ``event_type``) is rejected with
  ``400`` and a JSON ``{"error": "..."}`` payload describing what is
  wrong. Nothing is written to storage in this case.
* ``GET /collect`` is the classic "tracking pixel" fallback used by
  ``<img>`` beacons and browsers without ``fetch``/``sendBeacon``. A real
  tracking pixel must **never** break the host page, so this endpoint
  *always* returns ``200`` with a tiny GIF body, even when the supplied
  query parameters are missing or invalid. However, "never break the page"
  is not the same as "never validate": invalid GET events are validated
  with the exact same rules as POST and are silently dropped (not stored)
  rather than corrupting the raw_events table with garbage rows. Tests in
  ``tests/test_collect.py`` pin down this distinction explicitly.
"""
import json
from datetime import datetime

from flask import Blueprint, Response, request, jsonify

from .db import get_db
from .track_snippet import TRACK_JS

bp = Blueprint("collect", __name__)

# A valid, minimal 1x1 transparent GIF, used as the tracking-pixel response body.
_PIXEL_GIF = bytes(
    [
        0x47, 0x49, 0x46, 0x38, 0x39, 0x61, 0x01, 0x00, 0x01, 0x00, 0x80, 0x00,
        0x00, 0xFF, 0xFF, 0xFF, 0x00, 0x00, 0x00, 0x21, 0xF9, 0x04, 0x01, 0x00,
        0x00, 0x00, 0x00, 0x2C, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00,
        0x00, 0x02, 0x02, 0x44, 0x01, 0x00, 0x3B,
    ]
)

VALID_EVENT_TYPES = ("pageview", "custom")


@bp.route("/track.js")
def track_js():
    return Response(TRACK_JS, mimetype="application/javascript")


def _parse_timestamp(value):
    """Parse an ISO-8601 string or epoch seconds/milliseconds into a naive
    UTC ``datetime``. Raises ``ValueError`` for anything unparsable."""
    if value is None or value == "":
        raise ValueError("timestamp is required")

    if isinstance(value, (int, float)):
        return _from_epoch(value)

    text = str(value).strip()
    try:
        numeric = float(text)
    except ValueError:
        numeric = None
    if numeric is not None:
        return _from_epoch(numeric)

    try:
        iso_text = text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso_text)
        return dt.replace(tzinfo=None)
    except ValueError:
        raise ValueError(f"invalid timestamp: {value!r}")


def _from_epoch(numeric):
    try:
        if numeric > 1e12:  # milliseconds
            numeric /= 1000.0
        return datetime.utcfromtimestamp(numeric)
    except (OverflowError, OSError, ValueError):
        raise ValueError(f"invalid timestamp: {numeric!r}")


def validate_event(data):
    """Validate + normalise an incoming event.

    Returns ``(is_valid, error_message, normalized_dict_or_None)``.
    """
    if not isinstance(data, dict):
        return False, "request body must be a JSON object", None

    errors = []

    site_id = data.get("site_id")
    if not site_id or not isinstance(site_id, str):
        errors.append("site_id is required and must be a non-empty string")

    session_id = data.get("session_id")
    if not session_id or not isinstance(session_id, str):
        errors.append("session_id is required and must be a non-empty string")

    event_type = data.get("event_type") or "pageview"
    if event_type not in VALID_EVENT_TYPES:
        errors.append(f"event_type must be one of {VALID_EVENT_TYPES}")

    ts = None
    try:
        ts = _parse_timestamp(data.get("timestamp"))
    except ValueError as exc:
        errors.append(str(exc))

    if errors:
        return False, "; ".join(errors), None

    properties = data.get("properties")
    normalized = {
        "site_id": site_id,
        "session_id": session_id,
        "event_type": event_type,
        "event_name": data.get("event_name"),
        "page_url": data.get("page_url"),
        "referrer": data.get("referrer"),
        "user_agent": data.get("user_agent") or request.headers.get("User-Agent", ""),
        "timestamp": ts.isoformat(),
        "properties": json.dumps(properties) if properties is not None else None,
    }
    return True, None, normalized


def store_event(normalized):
    db = get_db()
    db.execute(
        """
        INSERT INTO raw_events
            (site_id, session_id, event_type, event_name, page_url,
             referrer, user_agent, timestamp, properties)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            normalized["site_id"],
            normalized["session_id"],
            normalized["event_type"],
            normalized["event_name"],
            normalized["page_url"],
            normalized["referrer"],
            normalized["user_agent"],
            normalized["timestamp"],
            normalized["properties"],
        ),
    )
    db.commit()


@bp.route("/collect", methods=["POST"])
def collect_post():
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "request body must be valid JSON"}), 400

    is_valid, error, normalized = validate_event(data)
    if not is_valid:
        return jsonify({"error": error}), 400

    store_event(normalized)
    return jsonify({"status": "ok"}), 200


@bp.route("/collect", methods=["GET"])
def collect_get():
    properties = None
    raw_properties = request.args.get("properties")
    if raw_properties:
        try:
            properties = json.loads(raw_properties)
        except ValueError:
            properties = None  # malformed properties on the pixel path are dropped, not fatal

    data = {
        "site_id": request.args.get("site_id"),
        "session_id": request.args.get("session_id"),
        "event_type": request.args.get("event_type", "pageview"),
        "event_name": request.args.get("event_name"),
        "page_url": request.args.get("page_url"),
        "referrer": request.args.get("referrer"),
        "user_agent": request.headers.get("User-Agent", ""),
        "timestamp": request.args.get("timestamp"),
        "properties": properties,
    }

    is_valid, _error, normalized = validate_event(data)
    if is_valid:
        store_event(normalized)
    # Contract: the pixel ALWAYS returns 200 + a 1x1 GIF, valid or not.
    # Invalid events are simply never written to storage (see module docstring).
    return Response(_PIXEL_GIF, mimetype="image/gif")
