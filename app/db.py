"""SQLite storage layer for Web Analytics Tracker.

Design notes
------------
* Every incoming event (pageview or custom) is stored as one row in
  ``raw_events`` exactly as received (after validation/normalisation).
* We never derive "sessions" at write time. Session boundaries are a
  *reporting-time* concept (see ``app/sessionize.py``) because the correct
  boundary depends on the configured inactivity timeout, and recomputing it
  from raw events keeps the write path simple and fast.
* For the test suite (``create_app(testing=True)``) we use an in-memory
  SQLite database. Because ``:memory:`` databases are private to the
  connection that created them, we keep a single long-lived connection on
  the Flask ``app`` object itself instead of opening a new one per request
  (which is what we do for the on-disk/production database via ``flask.g``).
"""
import sqlite3

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_name TEXT,
    page_url TEXT,
    referrer TEXT,
    user_agent TEXT,
    timestamp TEXT NOT NULL,
    properties TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_raw_events_site_session
    ON raw_events (site_id, session_id);
CREATE INDEX IF NOT EXISTS idx_raw_events_timestamp
    ON raw_events (timestamp);
"""


def _create_schema(conn):
    conn.executescript(SCHEMA)
    conn.commit()


def get_db():
    """Return a SQLite connection for the current app/request context."""
    db_path = current_app.config["DATABASE"]

    if db_path == ":memory:":
        # Keep one persistent connection per app instance so data survives
        # across requests within the same test/app run.
        if not hasattr(current_app, "_memory_db_conn"):
            conn = sqlite3.connect(":memory:", check_same_thread=False)
            conn.row_factory = sqlite3.Row
            _create_schema(conn)
            current_app._memory_db_conn = conn
        return current_app._memory_db_conn

    if "db" not in g:
        g.db = sqlite3.connect(db_path)
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_app(app):
    """Create the schema for on-disk databases and register teardown."""
    if app.config["DATABASE"] != ":memory:":
        conn = sqlite3.connect(app.config["DATABASE"])
        _create_schema(conn)
        conn.close()
    app.teardown_appcontext(close_db)
