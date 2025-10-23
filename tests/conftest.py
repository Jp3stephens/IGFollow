import json
import os
import sys
from typing import Dict, List, Optional

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app import db  # noqa: E402
from app.models import InstagramSession  # noqa: E402


class StubInstagramService:
    def __init__(self):
        self._available = True
        self._availability_error: Optional[str] = None
        self._connected_users: set[int] = set()
        self.relationships: Dict[str, List[Dict[str, str]]] = {
            "followers": [
                {
                    "username": "initialfollower",
                    "full_name": "Initial Follower",
                    "profile_pic_url": "https://img.local/initialfollower.jpg",
                }
            ],
            "following": [
                {
                    "username": "initialfollowing",
                    "full_name": "Initial Following",
                    "profile_pic_url": "https://img.local/initialfollowing.jpg",
                }
            ],
        }

    def init_app(self, app):
        app.extensions["instagram_service"] = self

    def is_available(self) -> bool:
        return self._available

    def availability_error(self) -> Optional[str]:
        return self._availability_error

    def is_connected(self, user) -> bool:
        return bool(user and user.id in self._connected_users)

    def connect_user(self, user, username: str, password: str) -> None:
        session = user.instagram_session or InstagramSession(user_id=user.id)
        session.instagram_username = username.strip("@")
        session.settings_json = json.dumps({"auth": "stub"})
        session.encrypted_password = "stub"
        db.session.add(session)
        db.session.commit()
        self._connected_users.add(user.id)

    def disconnect_user(self, user) -> None:
        if user.instagram_session:
            db.session.delete(user.instagram_session)
            db.session.commit()
        self._connected_users.discard(user.id)

    def fetch_profile(self, user, username: str):
        normalized = username.strip("@")
        return {
            "user_id": f"id-{normalized}",
            "username": normalized,
            "full_name": normalized.title(),
            "profile_pic_url": f"https://img.local/{normalized}.jpg",
        }

    def fetch_relationships(self, user, user_id: str, relationship: str):
        return list(self.relationships.get(relationship, []))

    def resolve_profile_picture(self, user, username: str) -> str:
        return f"https://img.local/{username}.jpg"

    # Helpers for tests
    def set_available(self, value: bool, error: Optional[str] = None) -> None:
        self._available = value
        self._availability_error = None if value else error

    def disconnect_all(self) -> None:
        self._connected_users.clear()


@pytest.fixture(autouse=True)
def stub_instagram(monkeypatch):
    import app.instagram as instagram_module
    import app.__init__ as app_module

    service = StubInstagramService()
    monkeypatch.setattr(instagram_module, "instagram_service", service)
    monkeypatch.setattr(app_module, "instagram_service", service)

    def _get_service():
        return service

    monkeypatch.setattr(instagram_module, "get_instagram_service", _get_service)
    yield service
