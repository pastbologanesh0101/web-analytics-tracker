"""The vanilla-JS snippet served at GET /track.js.

Usage on a tracked site::

    <script src="https://your-tracker.example.com/track.js"
            data-site-id="YOUR_SITE_ID" async></script>

Behaviour:
* Fires a "pageview" beacon automatically on load.
* Generates (and persists in localStorage) a client-side session id, so
  repeat visits within 30 minutes of inactivity are recognised as the
  same browsing session by the client. The server still re-derives real
  session boundaries independently (see app/sessionize.py) - the client
  id is only a hint.
* Exposes ``window.watTrack(eventName, properties)`` for custom events.
* Prefers ``navigator.sendBeacon``, falls back to ``fetch`` (POST JSON),
  and finally falls back to a classic 1x1 tracking-pixel <img> GET request
  so that tracking never breaks the host page even in very old browsers or
  when the network call itself fails.
"""

TRACK_JS = """
(function () {
  "use strict";
  var ENDPOINT = "/collect";
  var SESSION_KEY = "__wat_session_id";
  var SESSION_EXPIRY_KEY = "__wat_session_expiry";
  var SESSION_TIMEOUT_MS = 30 * 60 * 1000; // 30 minutes, mirrors server default

  function getSiteId() {
    var current = document.currentScript;
    if (current && current.getAttribute) {
      var id = current.getAttribute("data-site-id");
      if (id) return id;
    }
    var scripts = document.getElementsByTagName("script");
    for (var i = 0; i < scripts.length; i++) {
      var src = scripts[i].src || "";
      if (src.indexOf("/track.js") !== -1) {
        var attr = scripts[i].getAttribute("data-site-id");
        if (attr) return attr;
      }
    }
    return null;
  }

  function getOrCreateSessionId() {
    var now = Date.now();
    var sid = null;
    var expiry = 0;
    try {
      sid = window.localStorage.getItem(SESSION_KEY);
      expiry = parseInt(window.localStorage.getItem(SESSION_EXPIRY_KEY) || "0", 10);
    } catch (e) {
      /* localStorage unavailable (private mode, etc.) - fall back to a
         per-page id; the server will still see it as a fresh session. */
    }
    if (!sid || now > expiry) {
      sid = "sid_" + now.toString(36) + "_" + Math.random().toString(36).slice(2);
    }
    try {
      window.localStorage.setItem(SESSION_KEY, sid);
      window.localStorage.setItem(SESSION_EXPIRY_KEY, String(now + SESSION_TIMEOUT_MS));
    } catch (e) {
      /* ignore */
    }
    return sid;
  }

  function pixelFallback(payload) {
    var img = new Image(1, 1);
    var parts = [];
    for (var key in payload) {
      if (!Object.prototype.hasOwnProperty.call(payload, key)) continue;
      var value = payload[key];
      if (value === undefined || value === null) continue;
      if (typeof value === "object") value = JSON.stringify(value);
      parts.push(encodeURIComponent(key) + "=" + encodeURIComponent(value));
    }
    img.src = ENDPOINT + "?" + parts.join("&");
  }

  function send(payload) {
    var body = JSON.stringify(payload);

    if (navigator.sendBeacon) {
      try {
        var blob = new Blob([body], { type: "application/json" });
        var ok = navigator.sendBeacon(ENDPOINT, blob);
        if (ok) return;
      } catch (e) {
        /* fall through to fetch/pixel */
      }
    }

    if (window.fetch) {
      try {
        fetch(ENDPOINT, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: body,
          keepalive: true,
        }).catch(function () {
          pixelFallback(payload);
        });
        return;
      } catch (e) {
        /* fall through to pixel */
      }
    }

    pixelFallback(payload);
  }

  function track(eventType, eventName, properties) {
    var payload = {
      site_id: getSiteId(),
      session_id: getOrCreateSessionId(),
      event_type: eventType || "pageview",
      event_name: eventName || null,
      page_url: window.location.href,
      referrer: document.referrer || null,
      timestamp: new Date().toISOString(),
      properties: properties || null,
    };
    send(payload);
  }

  window.watTrack = function (eventName, properties) {
    track("custom", eventName, properties);
  };

  track("pageview");
})();
"""
