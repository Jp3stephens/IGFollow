import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest

from app.instagram import InstagramProfile, InstagramRelationship


class StubInstagramService:
    def __init__(self):
        self.is_configured = True
        self.relationships = {
            "followers": [
                InstagramRelationship(
                    username="initialfollower",
                    full_name="Initial Follower",
                    profile_pic_url="https://img.local/initialfollower.jpg",
                )
            ],
            "following": [
                InstagramRelationship(
                    username="initialfollowing",
                    full_name="Initial Following",
                    profile_pic_url="https://img.local/initialfollowing.jpg",
                )
            ],
        }

    def init_app(self, app):
        app.extensions["instagram_service"] = self

    def fetch_profile(self, username: str) -> InstagramProfile:
        normalized = username.strip("@")
        return InstagramProfile(
            user_id=f"id-{normalized}",
            username=normalized,
            full_name=normalized.title(),
            profile_pic_url=f"https://img.local/{normalized}.jpg",
        )

    def fetch_relationships(self, user_id: str, relationship: str):
        return list(self.relationships.get(relationship, []))

    def resolve_profile_picture(self, username: str) -> str:
        return f"https://img.local/{username}.jpg"


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
