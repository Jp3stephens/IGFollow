import io
from html.parser import HTMLParser

import pytest

from app import create_app, db
from app.config import Config


class CsrfExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.token = None

    def handle_starttag(self, tag, attrs):
        if tag != "input":
            return
        attr_map = dict(attrs)
        if attr_map.get("name") == "csrf_token":
            self.token = attr_map.get("value")


def extract_csrf_token(html: str) -> str:
    parser = CsrfExtractor()
    parser.feed(html)
    if not parser.token:
        raise AssertionError("csrf token missing from response")
    return parser.token


class LiveConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SECRET_KEY = "integration-secret"


@pytest.fixture
def app():
    app = create_app(LiveConfig)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def test_full_flow_with_csrf(client):
    # Register
    resp = client.get("/register")
    token = extract_csrf_token(resp.get_data(as_text=True))
    resp = client.post(
        "/register",
        data={
            "csrf_token": token,
            "email": "owner@example.com",
            "password": "Secret123!",
            "confirm_password": "Secret123!",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200

    # Log out to reset the session so we can exercise the login flow as well
    client.get("/logout", follow_redirects=True)

    # Login
    resp = client.get("/login")
    token = extract_csrf_token(resp.get_data(as_text=True))
    resp = client.post(
        "/login",
        data={"csrf_token": token, "email": "owner@example.com", "password": "Secret123!"},
        follow_redirects=True,
    )
    assert resp.status_code == 200

    # Add account
    resp = client.get("/accounts/add")
    token = extract_csrf_token(resp.get_data(as_text=True))
    resp = client.post(
        "/accounts/add",
        data={"csrf_token": token, "username": "demoaccount"},
        follow_redirects=True,
    )
    assert resp.status_code == 200

    # Upload snapshot
    resp = client.get("/accounts/1")
    token = extract_csrf_token(resp.get_data(as_text=True))
    csv_data = "username,full_name\nalice,Alice\nbob,Bob\n"
    resp = client.post(
        "/accounts/1/upload",
        data={
            "csrf_token": token,
            "snapshot_type": "followers",
            "snapshot_file": (io.BytesIO(csv_data.encode("utf-8")), "followers.csv"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "@alice" in resp.get_data(as_text=True)

    # Trigger export via AJAX-style request
    resp = client.get("/accounts/1")
    token = extract_csrf_token(resp.get_data(as_text=True))
    resp = client.post(
        "/accounts/1/export",
        data={
            "csrf_token": token,
            "snapshot_type": "followers",
            "export_format": "csv",
        },
        headers={
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json",
            "X-CSRFToken": token,
        },
    )

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["status"] == "ok"
    assert payload["download_url"].startswith("/accounts/1/export/download")

    download = client.get(payload["download_url"])
    assert download.status_code == 200
    assert "attachment" in download.headers.get("Content-Disposition", "")
    body = download.get_data(as_text=True)
    assert "alice" in body and "bob" in body
