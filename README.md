# Web Analytics Tracker

[![tests](https://github.com/pastbologanesh0101/web-analytics-tracker/actions/workflows/tests.yml/badge.svg)](https://github.com/pastbologanesh0101/web-analytics-tracker/actions/workflows/tests.yml)

A small, self-contained Google-Analytics-style service: a JS snippet you
embed on a site, a Flask ingestion endpoint that records pageviews/custom
events, and a set of reporting endpoints (+ a tiny dashboard) that turn the
raw event stream into sessions, top pages/referrers, and bounce rate.

## Architecture

```
Browser (embed) --GET /track.js--> Flask app --serves snippet-->
   snippet fires beacons --POST /collect (JSON) or GET /collect (pixel)-->
      raw_events table (SQLite)
         |
         v
   app/sessionize.py: derive_sessions() groups raw events into REAL
   sessions (splits on inactivity gaps) at *read* time
         |
         v
   app/reporting.py: aggregates sessionized events into
   /report/* JSON endpoints + /dashboard HTML
```

* **`app/collect.py`** - `/track.js` snippet + `/collect` ingestion (GET and
  POST), including all input validation.
* **`app/sessionize.py`** - pure function that turns a raw event stream into
  session-bounded events. No I/O, no Flask - easy to unit test directly.
* **`app/reporting.py`** - loads raw events (optionally filtered by
  `site_id`), sessionizes them, and computes each report.
* **`app/db.py`** - tiny SQLite wrapper. On-disk DB for normal use (one
  connection per request, via `flask.g`); a single persistent in-memory
  connection when `create_app(testing=True)` is used, so state survives
  across requests within a test.
* **`app/__init__.py`** - the app factory, `create_app(testing=False,
  db_path=None)`.

Only one table is needed, `raw_events` - every pageview/custom event is a
row. Sessions are *derived*, not stored, so the session-boundary rule can
change without any migration.

## Embedding the tracker on a site

```html
<script src="https://your-tracker.example.com/track.js"
        data-site-id="YOUR_SITE_ID" async></script>
```

This automatically fires a `pageview` beacon on load. It also generates a
session id, persisted in `localStorage`, that is refreshed on every beacon
with a 30-minute sliding expiry (this is a client-side hint only - the
server independently re-derives real session boundaries, see below).

To track a custom event from your own JS:

```html
<script>
  watTrack('signup_completed', { plan: 'pro' });
</script>
```

The snippet sends beacons via `navigator.sendBeacon` first, falls back to
`fetch(..., { keepalive: true })`, and finally falls back to a classic
1x1 `<img>` pixel GET request - so tracking never throws inside the host
page, no matter how old the browser is or whether the network call itself
fails.

## API

### `GET /track.js`
Serves the tracking snippet as `application/javascript`.

### `POST /collect`
Body (JSON):

```json
{
  "site_id": "site-123",
  "session_id": "sid_abc123",
  "event_type": "pageview",
  "event_name": null,
  "page_url": "https://example.com/pricing",
  "referrer": "https://google.com",
  "timestamp": "2026-01-15T10:32:00Z",
  "properties": { "plan": "pro" }
}
```

* `site_id`, `session_id`, and a parseable `timestamp` (ISO-8601 or epoch
  seconds/milliseconds) are **required**. `event_type` defaults to
  `"pageview"` and must be `"pageview"` or `"custom"`.
* Success: `200 {"status": "ok"}`.
* Failure: `400 {"error": "<human-readable reason(s)>"}` - **nothing is
  written to storage**.

### `GET /collect`
Same fields as query parameters (`properties` as a JSON-encoded string).
This is the tracking-pixel fallback used by `<img>` beacons.

**Validation contract - read this carefully:**
* This endpoint **always returns `200` with a 1x1 GIF body**, valid input
  or not. A real tracking pixel must never surface an error to the host
  page (imagine a broken pixel throwing a console error on every customer's
  site).
* "Never break the page" is *not* the same as "never validate". Internally
  the exact same validation used by `POST /collect` runs first; if it
  fails, the event is silently **dropped** - not written to `raw_events` -
  and the 200/GIF response is still returned. Bad GET params can never
  corrupt stored data; they just don't get recorded.
* This distinction is pinned down explicitly in
  `tests/test_collect.py` (`test_get_collect_pixel_always_returns_200_even_with_missing_fields`
  and `test_get_collect_pixel_with_bad_timestamp_does_not_corrupt_storage`).

### Reporting endpoints
All accept an optional `?site_id=...` query parameter to scope the report;
omitting it reports across all sites.

| Endpoint | Returns |
|---|---|
| `GET /report/pageviews` | `{ "YYYY-MM-DD": count, ... }` - pageviews per day |
| `GET /report/sessions` | `{ "YYYY-MM-DD": count, ... }` - sessions per day, bucketed by each session's first event |
| `GET /report/top-pages` | `[{ "page_url": ..., "pageviews": N }, ...]` sorted desc |
| `GET /report/top-referrers` | `[{ "referrer": ..., "sessions": N }, ...]` - ranked by number of *sessions* that referrer initiated (the referrer on each session's first pageview), not raw hit count |
| `GET /report/bounce-rate` | `{ "total_sessions": N, "bounced_sessions": N, "bounce_rate": 0.0-1.0 }` |
| `GET /report/events` | `{ "event_name": count, ... }` - custom event breakdown |
| `GET /dashboard` | a minimal HTML page that renders all of the above for a given site id |

## How session boundaries are computed

A "session" is **not** the same thing as a raw `session_id`. Real events
are grouped by `(site_id, session_id)` and sorted by time; a new session
starts whenever the gap between two consecutive events for that id exceeds
the configured inactivity timeout (`SESSION_TIMEOUT_MINUTES`, default 30).
So if a `session_id` is reused after, say, a 2-hour gap, it produces **two**
separate sessions for reporting purposes, exactly the way Google Analytics
defines a session. This logic lives in `app/sessionize.py::derive_sessions`,
is pure (no DB/Flask dependency), and is unit-tested directly in
`tests/test_sessionize.py`.

## How bounce rate is computed

```
bounce_rate = (sessions with exactly one pageview) / (total sessions)
```

computed *after* session derivation, so a `session_id` that was really two
separate visits is correctly counted as two (possibly bounced) sessions
rather than one long session. See `compute_bounce_rate` in
`app/reporting.py`.

## Running it

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py            # http://127.0.0.1:5000, dashboard at /dashboard
```

## Running the tests

```bash
pip install -r requirements-dev.txt
pytest -v
```

19 tests cover: valid POST ingestion, malformed POST rejection (missing
`site_id`, bad timestamp, non-JSON body), the GET-pixel "never break the
page but never corrupt storage" contract, session-boundary splitting vs.
merging, daily pageview bucketing, top-pages ranking, top-referrers
ranking, bounce rate (including a session-split scenario), and custom
event breakdown.

CI (`.github/workflows/tests.yml`) runs the same suite on Python 3.11 and
3.12 on every push and pull request.

## License

MIT - see [LICENSE](LICENSE).
