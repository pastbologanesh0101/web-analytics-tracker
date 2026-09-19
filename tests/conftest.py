import pytest

from app import create_app


@pytest.fixture
def app():
    """Fresh Flask app with a fresh in-memory SQLite DB for every test."""
    return create_app(testing=True)


@pytest.fixture
def client(app):
    return app.test_client()
