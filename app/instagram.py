"""Integration with the Instagram API via instagrapi."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from flask import current_app

try:  # pragma: no cover - imported lazily in tests
    from instagrapi import Client
    from instagrapi.exceptions import LoginRequired
except Exception:  # pragma: no cover - dependency may be missing during docs builds
    Client = None  # type: ignore
    LoginRequired = Exception  # type: ignore


LOGGER = logging.getLogger(__name__)


class InstagramServiceError(RuntimeError):
    """Raised when the Instagram service cannot fulfil a request."""


@dataclass
class InstagramProfile:
    user_id: str
    username: str
    full_name: str
    profile_pic_url: str


@dataclass
class InstagramRelationship:
    username: str
    full_name: str
    profile_pic_url: str


class InstagramService:
    """Thin wrapper around instagrapi with lazy authentication and caching."""

    def __init__(self) -> None:
        self._client: Optional[Client] = None
        self._username: Optional[str] = None
        self._password: Optional[str] = None
        self._configured = False

    def init_app(self, app) -> None:
        app.extensions["instagram_service"] = self
        username = app.config.get("INSTAGRAM_USERNAME")
        password = app.config.get("INSTAGRAM_PASSWORD")
        if username and password:
            self.configure(username, password)

    def configure(self, username: str, password: str) -> None:
        self._username = username
        self._password = password
        self._configured = bool(username and password)
        self._client = None

    @property
    def is_configured(self) -> bool:
        return self._configured

    def _client_or_raise(self) -> Client:
        if Client is None:
            raise InstagramServiceError(
                "instagrapi is not installed. Please install dependencies."
            )

        if not self._configured:
            raise InstagramServiceError(
                "Instagram credentials are not configured. Set INSTAGRAM_USERNAME and INSTAGRAM_PASSWORD."
            )

        if self._client is None:
            self._client = Client()
            self._login()
        return self._client

    def _login(self) -> None:
        assert self._client is not None
        try:
            self._client.login(self._username, self._password)
        except LoginRequired as exc:  # pragma: no cover - defensive retry path
            LOGGER.warning("Instagram login required again: %s", exc)
            self._client.login(self._username, self._password)

    def fetch_profile(self, username: str) -> InstagramProfile:
        client = self._client_or_raise()
        try:
            info = client.user_info_by_username(username)
        except Exception as exc:  # pragma: no cover - surfaced through error messaging
            raise InstagramServiceError(f"Failed to fetch profile for @{username}: {exc}") from exc

        return InstagramProfile(
            user_id=str(info.pk),
            username=info.username,
            full_name=info.full_name or "",
            profile_pic_url=getattr(info, "profile_pic_url", ""),
        )

    def fetch_relationships(self, user_id: str, relationship: str) -> list[InstagramRelationship]:
        client = self._client_or_raise()
        fetch_limit = int(current_app.config.get("INSTAGRAM_FETCH_LIMIT", 2000))
        try:
            if relationship == "followers":
                data = client.user_followers(user_id, amount=fetch_limit)
            else:
                data = client.user_following(user_id, amount=fetch_limit)
        except Exception as exc:  # pragma: no cover - bubbled up with messaging
            raise InstagramServiceError(f"Failed to fetch {relationship}: {exc}") from exc

        results: list[InstagramRelationship] = []
        for entry in data.values():
            results.append(
                InstagramRelationship(
                    username=entry.username,
                    full_name=entry.full_name or "",
                    profile_pic_url=getattr(entry, "profile_pic_url", ""),
                )
            )
        return results

    @lru_cache(maxsize=512)
    def resolve_profile_picture(self, username: str) -> str:
        try:
            profile = self.fetch_profile(username)
            return profile.profile_pic_url
        except InstagramServiceError:
            return ""


instagram_service = InstagramService()


def get_instagram_service() -> InstagramService:
    service: InstagramService = current_app.extensions.get("instagram_service", instagram_service)
    return service
