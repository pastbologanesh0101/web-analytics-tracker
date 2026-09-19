"""Application factory for Web Analytics Tracker."""
import os

from flask import Flask

from . import db as db_module

DEFAULT_SESSION_TIMEOUT_MINUTES = 30


def create_app(testing=False, db_path=None):
    app = Flask(__name__)
    app.config["TESTING"] = bool(testing)
    app.config["SESSION_TIMEOUT_MINUTES"] = DEFAULT_SESSION_TIMEOUT_MINUTES

    if testing:
        app.config["DATABASE"] = db_path or ":memory:"
    else:
        default_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "analytics.db"
        )
        app.config["DATABASE"] = db_path or default_path

    db_module.init_app(app)

    from .collect import bp as collect_bp
    from .reporting import bp as reporting_bp

    app.register_blueprint(collect_bp)
    app.register_blueprint(reporting_bp)

    @app.route("/")
    def index():
        return {
            "service": "web-analytics-tracker",
            "endpoints": [
                "GET /track.js",
                "POST /collect",
                "GET /collect",
                "GET /report/pageviews",
                "GET /report/sessions",
                "GET /report/top-pages",
                "GET /report/top-referrers",
                "GET /report/bounce-rate",
                "GET /report/events",
                "GET /dashboard",
            ],
        }

    return app
