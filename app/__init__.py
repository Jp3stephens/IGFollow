from datetime import datetime
import os
from typing import Optional

from flask import Flask, flash, jsonify, redirect, request, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_wtf import CSRFProtect
from sqlalchemy.engine import make_url
from flask_wtf.csrf import CSRFError

from .config import Config
from .instagram import instagram_service


db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()


def create_app(config_class: type = Config) -> Flask:
    base_dir = os.path.abspath(os.path.dirname(__file__))
    app = Flask(
        __name__,
        static_folder=os.path.join(base_dir, "..", "static"),
        template_folder=os.path.join(base_dir, "..", "templates"),
    )
    app.config.from_object(config_class)

    try:
        os.makedirs(app.instance_path, exist_ok=True)
    except OSError:
        pass

    _ensure_sqlite_directory(app)

    instagram_service.init_app(app)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "warning"

    from . import models  # noqa: F401
    from .auth import auth_bp
    from .views import main_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)

    @app.context_processor
    def inject_globals():
        return {
            "now": datetime.utcnow(),
            "max_free_export": app.config.get("MAX_FREE_EXPORT", 600),
        }

    @app.errorhandler(CSRFError)
    def handle_csrf_error(error: CSRFError):  # pragma: no cover - exercised in integration tests
        message = error.description or "Your session expired. Please refresh and try again."
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.accept_mimetypes.accept_json:
            return jsonify({"status": "error", "message": message}), 400
        flash(message, "danger")
        referer = request.headers.get("Referer")
        return redirect(referer or url_for("main.dashboard"))

    return app


def _ensure_sqlite_directory(app: Flask) -> None:
    """Create the parent directory for SQLite databases if needed."""

    database_uri: Optional[str] = app.config.get("SQLALCHEMY_DATABASE_URI")
    if not database_uri:
        return

    try:
        url = make_url(database_uri)
    except Exception:  # pragma: no cover - defensive guard for invalid URIs
        return

    if url.drivername != "sqlite":
        return

    database = url.database
    if not database or database == ":memory:":
        return

    if not os.path.isabs(database):
        project_root = os.path.abspath(os.path.join(app.root_path, os.pardir))
        database = os.path.abspath(os.path.join(project_root, database))
        url = url.set(database=database)
        app.config["SQLALCHEMY_DATABASE_URI"] = str(url)

    directory = os.path.dirname(database)
    if directory:
        os.makedirs(directory, exist_ok=True)
