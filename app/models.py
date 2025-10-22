from datetime import datetime
from typing import Optional

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from . import db, login_manager


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_subscribed = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    tracked_accounts = db.relationship("TrackedAccount", back_populates="owner", cascade="all, delete-orphan")
    instagram_session = db.relationship(
        "InstagramSession",
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password, method="pbkdf2:sha256")

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class TrackedAccount(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    instagram_username = db.Column(db.String(255), nullable=False)
    instagram_user_id = db.Column(db.String(64), nullable=True)
    profile_picture_url = db.Column(db.String(512), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    owner = db.relationship("User", back_populates="tracked_accounts")
    snapshots = db.relationship("Snapshot", back_populates="tracked_account", cascade="all, delete-orphan", order_by="Snapshot.created_at")

    def latest_snapshot(self, snapshot_type: str) -> Optional["Snapshot"]:
        return (
            Snapshot.query.filter_by(tracked_account_id=self.id, snapshot_type=snapshot_type)
            .order_by(Snapshot.created_at.desc())
            .first()
        )

    @property
    def profile_image_url(self) -> str:
        """Return a best-effort URL for the Instagram avatar."""
        if self.profile_picture_url:
            return self.profile_picture_url
        return f"https://unavatar.io/instagram/{self.instagram_username}"  # pragma: no cover - simple helper


class Snapshot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tracked_account_id = db.Column(db.Integer, db.ForeignKey("tracked_account.id"), nullable=False)
    snapshot_type = db.Column(db.String(32), nullable=False)  # followers or following
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    tracked_account = db.relationship("TrackedAccount", back_populates="snapshots")
    entries = db.relationship("SnapshotEntry", back_populates="snapshot", cascade="all, delete-orphan")


class SnapshotEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    snapshot_id = db.Column(db.Integer, db.ForeignKey("snapshot.id"), nullable=False)
    username = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(255), nullable=True)
    profile_pic_url = db.Column(db.String(512), nullable=True)

    snapshot = db.relationship("Snapshot", back_populates="entries")


class InstagramSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, unique=True)
    instagram_username = db.Column(db.String(255), nullable=False)
    settings_json = db.Column(db.Text, nullable=False)
    encrypted_password = db.Column(db.Text, nullable=True)
    last_login_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", back_populates="instagram_session")


@login_manager.user_loader
def load_user(user_id: str) -> Optional[User]:
    return User.query.get(int(user_id))
