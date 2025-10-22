from __future__ import annotations

import pytest

from app import create_app, db
from app.config import Config
from app.models import Snapshot, SnapshotEntry, TrackedAccount, User


class ExportTestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    SECRET_KEY = "testing-secret"
    SECURITY_PASSWORD_SALT = "testing-salt"


@pytest.fixture
def app():
    app = create_app(ExportTestConfig)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def _seed_account() -> tuple[User, TrackedAccount, Snapshot]:
    user = User(email="owner@example.com")
    user.set_password("secret123")
    db.session.add(user)
    db.session.flush()

    account = TrackedAccount(user_id=user.id, instagram_username="igfollowdemo")
    db.session.add(account)
    db.session.flush()

    snapshot = Snapshot(tracked_account_id=account.id, snapshot_type="followers")
    db.session.add(snapshot)
    db.session.flush()

    entries = [
        SnapshotEntry(snapshot_id=snapshot.id, username="alice", full_name="Alice"),
        SnapshotEntry(snapshot_id=snapshot.id, username="bob", full_name="Bob"),
    ]
    db.session.add_all(entries)
    db.session.commit()

    return user, account, snapshot


def test_ajax_export_provides_download_url(app, client):
    with app.app_context():
        user, account, snapshot = _seed_account()
        user_email = user.email
        account_id = account.id

    login_response = client.post(
        "/login",
        data={"email": user_email, "password": "secret123"},
        follow_redirects=True,
    )
    assert login_response.status_code == 200

    response = client.post(
        f"/accounts/{account_id}/export",
        data={"snapshot_type": "followers", "export_format": "csv"},
        headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "ok"
    assert payload["download_url"].startswith(f"/accounts/{account_id}/export/download")

    download_response = client.get(payload["download_url"])
    assert download_response.status_code == 200
    assert download_response.mimetype == "text/csv"
    assert "attachment" in download_response.headers.get("Content-Disposition", "")
    body = download_response.get_data(as_text=True)
    assert "alice" in body and "bob" in body


def test_ajax_export_truncates_when_over_limit(app, client):
    with app.app_context():
        user, account, snapshot = _seed_account()
        user_email = user.email
        account_id = account.id
        # Pad entries beyond the free threshold
        for idx in range(605):
            db.session.add(
                SnapshotEntry(
                    snapshot_id=snapshot.id,
                    username=f"extra{idx}",
                    full_name=f"Extra {idx}",
                )
            )
        db.session.commit()

    login_response = client.post(
        "/login",
        data={"email": user_email, "password": "secret123"},
        follow_redirects=True,
    )
    assert login_response.status_code == 200

    response = client.post(
        f"/accounts/{account_id}/export",
        data={"snapshot_type": "followers", "export_format": "csv"},
        headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "ok"
    assert payload.get("limited") is True
    assert payload.get("exported_rows") == app.config.get("MAX_FREE_EXPORT", 600)
    assert payload.get("total_rows") > payload.get("exported_rows")
    assert "Free plan exports" in (payload.get("message") or "")

    download_response = client.get(payload["download_url"])
    assert download_response.status_code == 200

    body = download_response.get_data(as_text=True).strip().splitlines()
    # header + limited rows
    assert len(body) == payload["exported_rows"] + 1
