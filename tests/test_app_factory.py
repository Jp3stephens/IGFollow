import os
from uuid import uuid4

from sqlalchemy.engine import make_url

from app import create_app
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
