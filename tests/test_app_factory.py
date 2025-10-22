import os
from uuid import uuid4

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from app import create_app, db
from app.config import Config


def test_relative_sqlite_path_is_materialized():
    db_name = f"test_factory_{uuid4().hex}.db"

    class _RelativeSQLiteConfig(Config):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///instance/{db_name}"

    app = create_app(_RelativeSQLiteConfig)

    url = make_url(app.config["SQLALCHEMY_DATABASE_URI"])

    assert os.path.isabs(url.database)
    assert url.database.endswith(os.path.join("instance", db_name))
    assert os.path.isdir(os.path.dirname(url.database))


def test_startup_schema_migrations_add_missing_columns(tmp_path):
    legacy_db = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{legacy_db}")

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE user (
                    id INTEGER PRIMARY KEY,
                    email VARCHAR(255) NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    is_subscribed BOOLEAN,
                    created_at DATETIME
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE tracked_account (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    instagram_username VARCHAR(255) NOT NULL,
                    created_at DATETIME
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE snapshot (
                    id INTEGER PRIMARY KEY,
                    tracked_account_id INTEGER NOT NULL,
                    snapshot_type VARCHAR(32) NOT NULL,
                    created_at DATETIME
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE snapshot_entry (
                    id INTEGER PRIMARY KEY,
                    snapshot_id INTEGER NOT NULL,
                    username VARCHAR(255) NOT NULL
                )
                """
            )
        )

    class _LegacyConfig(Config):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{legacy_db}"

    app = create_app(_LegacyConfig)

    with app.app_context():
        inspector = inspect(db.engine)
        tracked_columns = {column["name"] for column in inspector.get_columns("tracked_account")}
        entry_columns = {column["name"] for column in inspector.get_columns("snapshot_entry")}

    assert {"instagram_user_id", "profile_picture_url"}.issubset(tracked_columns)
    assert {"full_name", "profile_pic_url"}.issubset(entry_columns)
