"""Integration with the Instagram API via instagrapi with per-user sessions."""

from __future__ import annotations

import base64
import json
import logging
from datetime import datetime
from functools import lru_cache
from typing import Optional

try:  # pragma: no cover - optional dependency in tests
    from cryptography.fernet import Fernet
except Exception:  # pragma: no cover - dependency may be missing in lightweight test environments
    Fernet = None  # type: ignore
from flask import current_app

from . import db
from .models import InstagramSession, User

INSTAGRAM_IMPORT_ERROR: Optional[str]
try:  # pragma: no cover - imported lazily in tests
    from instagrapi import Client
    from instagrapi.exceptions import LoginRequired
    INSTAGRAM_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - dependency may be missing during docs builds
    Client = None  # type: ignore
    LoginRequired = Exception  # type: ignore
    INSTAGRAM_IMPORT_ERROR = str(exc)


LOGGER = logging.getLogger(__name__)


class InstagramServiceError(RuntimeError):
    """Raised when the Instagram service cannot fulfil a request."""


class InstagramService:
    """Manage per-user authenticated sessions against the Instagram API."""

    def __init__(self) -> None:
        self._client_cache: dict[int, Client] = {}
        self._import_error: Optional[str] = INSTAGRAM_IMPORT_ERROR

    def init_app(self, app) -> None:
        app.extensions["instagram_service"] = self

    def is_available(self) -> bool:
        return self._attempt_import()

    def availability_error(self) -> Optional[str]:
        self._attempt_import()
        return self._import_error

    def _attempt_import(self) -> bool:
        global Client, LoginRequired

        if Client is not None:
            self._import_error = None
            return True

        try:  # pragma: no cover - exercised indirectly in environments without dependencies
            from instagrapi import Client as ClientType
            from instagrapi.exceptions import LoginRequired as LoginRequiredType
        except Exception as exc:  # pragma: no cover - surfaced through UI messaging
            self._import_error = str(exc)
            Client = None  # type: ignore
            LoginRequired = Exception  # type: ignore
            return False

        Client = ClientType  # type: ignore
        LoginRequired = LoginRequiredType  # type: ignore
        self._import_error = None
        return True

    def _require_available(self) -> None:
        if self._attempt_import():
            return

        message = (
            "Instagram integration is unavailable. Install instagrapi and cryptography to enable syncing."
        )
        if self._import_error:
            message = f"{message} ({self._import_error})"
        raise InstagramServiceError(message)

    def is_connected(self, user: User) -> bool:
        return bool(user.instagram_session and user.instagram_session.settings_json)

    def connect_user(self, user: User, username: str, password: str) -> None:
        self._require_available()

        username = username.strip().lstrip("@")
        if not username or not password:
            raise InstagramServiceError("Instagram username and password are required.")

        if Fernet is None:
            raise InstagramServiceError(
                "cryptography is required to encrypt Instagram credentials. Install the optional dependency to connect."
            )

        client = Client()  # type: ignore[call-arg]
        try:
            client.login(username, password)
        except Exception as exc:  # pragma: no cover - network failures bubbled up
            raise InstagramServiceError(f"Instagram login failed: {exc}") from exc

        settings = self._serialize_settings(client)
        encrypted_password = self._encrypt(password)

        session = user.instagram_session or InstagramSession(user_id=user.id)
        session.instagram_username = username
        session.settings_json = json.dumps(settings)
        session.encrypted_password = encrypted_password
        session.last_login_at = datetime.utcnow()
        db.session.add(session)
        db.session.commit()

        self._client_cache.pop(user.id, None)

    def disconnect_user(self, user: User) -> None:
        if not user.instagram_session:
            return
        db.session.delete(user.instagram_session)
        db.session.commit()
        user.instagram_session = None
        self._client_cache.pop(user.id, None)

    def fetch_profile(self, user: User, username: str):
        client = self._client_for(user)
        try:
            info = client.user_info_by_username(username)
        except Exception as exc:  # pragma: no cover - surfaced through error messaging
            raise InstagramServiceError(f"Failed to fetch profile for @{username}: {exc}") from exc

        return {
            "user_id": str(info.pk),
            "username": info.username,
            "full_name": info.full_name or "",
            "profile_pic_url": getattr(info, "profile_pic_url", ""),
        }

    def fetch_relationships(self, user: User, user_id: str, relationship: str):
        client = self._client_for(user)
        fetch_limit = int(current_app.config.get("INSTAGRAM_FETCH_LIMIT", 2000))
        try:
            if relationship == "followers":
                data = client.user_followers(user_id, amount=fetch_limit)
            else:
                data = client.user_following(user_id, amount=fetch_limit)
        except Exception as exc:  # pragma: no cover - bubbled up with messaging
            raise InstagramServiceError(f"Failed to fetch {relationship}: {exc}") from exc

        results = []
        for entry in data.values():
            results.append(
                {
                    "username": entry.username,
                    "full_name": entry.full_name or "",
                    "profile_pic_url": getattr(entry, "profile_pic_url", ""),
                }
            )
        return results

    def resolve_profile_picture(self, user: User, username: str) -> str:
        if not self.is_connected(user):
            return ""
        try:
            profile = self.fetch_profile(user, username)
            return profile["profile_pic_url"]
        except InstagramServiceError:
            return ""

    def _client_for(self, user: User) -> Client:
        self._require_available()

        cached = self._client_cache.get(user.id)
        if cached is not None:
            return cached

        session = user.instagram_session
        if not session or not session.settings_json:
            raise InstagramServiceError(
                "Connect your Instagram account to sync followers and following automatically."
            )

        settings = json.loads(session.settings_json)
        client = Client()
        client.set_settings(settings)

        try:
            client.user_info_by_username(session.instagram_username)
        except LoginRequired:
            password = self._decrypt(session.encrypted_password)
            if not password:
                raise InstagramServiceError(
                    "Instagram session expired. Reconnect your account to continue syncing."
                )
            client.login(session.instagram_username, password)
            session.settings_json = json.dumps(self._serialize_settings(client))
            session.last_login_at = datetime.utcnow()
            db.session.add(session)
            db.session.commit()
        except Exception as exc:  # pragma: no cover - unexpected authentication issues
            LOGGER.warning("Instagram session validation failed: %s", exc)

        self._client_cache[user.id] = client
        return client

    def _serialize_settings(self, client) -> dict:
        """Return a serializable settings payload from the Instagram client."""

        if hasattr(client, "get_settings"):
            try:
                settings = client.get_settings()
                if settings is not None:
                    return settings
            except TypeError:
                # Older instagrapi builds expose get_settings without optional args but
                # still allow falling back to dump_settings below.
                pass

        if hasattr(client, "settings"):
            settings_obj = client.settings
            if callable(getattr(settings_obj, "dict", None)):
                return settings_obj.dict()
            if isinstance(settings_obj, dict):
                return settings_obj

        if hasattr(client, "dump_settings"):
            try:
                return client.dump_settings()  # type: ignore[misc]
            except TypeError:
                # Some instagrapi versions require a filesystem path; when encountered we
                # fall back to the in-memory representation obtained via the settings
                # attribute above. If neither are available, surface a clear error.
                pass

        raise InstagramServiceError(
            "Unable to serialise Instagram session settings with the installed instagrapi version."
        )

    def _encrypt(self, value: str) -> str:
        if not value:
            return ""
        return self._fernet().encrypt(value.encode()).decode()

    def _decrypt(self, value: Optional[str]) -> str:
        if not value:
            return ""
        try:
            return self._fernet().decrypt(value.encode()).decode()
        except Exception:  # pragma: no cover - corrupted secrets fall back to reconnect flow
            return ""

    @lru_cache(maxsize=1)
    def _fernet(self) -> Fernet:
        if Fernet is None:
            raise InstagramServiceError(
                "cryptography is required to encrypt Instagram credentials. Install the optional dependency to connect."
            )

        secret = current_app.config.get("SECRET_KEY")
        if not secret:
            raise RuntimeError("SECRET_KEY is required for Instagram session encryption")
        import hashlib

        digest = hashlib.sha256(secret.encode("utf-8")).digest()
        key = base64.urlsafe_b64encode(digest)
        return Fernet(key)


instagram_service = InstagramService()


def get_instagram_service() -> InstagramService:
    service: InstagramService = current_app.extensions.get("instagram_service", instagram_service)
    return service
