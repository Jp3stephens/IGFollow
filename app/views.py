from __future__ import annotations

import io
from datetime import datetime
from typing import Iterable, Optional

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required
from itsdangerous import BadSignature, URLSafeTimedSerializer

from . import db
from .diff import SnapshotDiff, compute_diff
from .forms import (
    ValidationError,
    parse_snapshot_file,
    validate_export_format,
    validate_snapshot_type,
)
from .models import Snapshot, SnapshotEntry, TrackedAccount
from .paywall import exceeds_free_limit


main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def landing_page():
    return render_template("landing.html")


@main_bp.route("/dashboard")
@login_required
def dashboard():
    accounts = (
        TrackedAccount.query.filter_by(user_id=current_user.id)
        .order_by(TrackedAccount.created_at.desc())
        .all()
    )
    return render_template("dashboard.html", accounts=accounts)


@main_bp.route("/accounts/add", methods=["GET", "POST"])
@login_required
def add_account():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        notes = request.form.get("notes", "")
        if not username:
            flash("Instagram username is required.", "danger")
        else:
            existing = TrackedAccount.query.filter_by(
                user_id=current_user.id, instagram_username=username
            ).first()
            if existing:
                flash("You are already tracking this account.", "warning")
                return redirect(url_for("main.view_account", account_id=existing.id))

            account = TrackedAccount(
                user_id=current_user.id,
                instagram_username=username,
                notes=notes or None,
            )
            db.session.add(account)
            db.session.commit()
            flash("Account added. Upload your first snapshot to begin tracking.", "success")
            return redirect(url_for("main.view_account", account_id=account.id))

    return render_template("accounts/add.html")


@main_bp.route("/accounts/<int:account_id>")
@login_required
def view_account(account_id: int):
    account = _get_account_or_404(account_id)
    followers = _latest_diff(account, "followers")
    following = _latest_diff(account, "following")
    return render_template(
        "accounts/detail.html",
        account=account,
        followers_diff=followers,
        following_diff=following,
    )


def _latest_diff(account: TrackedAccount, snapshot_type: str) -> Optional[SnapshotDiff]:
    latest = account.latest_snapshot(snapshot_type)
    if not latest:
        return None

    previous = (
        Snapshot.query.filter(
            Snapshot.tracked_account_id == account.id,
            Snapshot.snapshot_type == snapshot_type,
            Snapshot.created_at < latest.created_at,
        )
        .order_by(Snapshot.created_at.desc())
        .first()
    )
    if not previous:
        return SnapshotDiff(added=[entry.username for entry in latest.entries], removed=[])

    return compute_diff(
        (entry.username for entry in previous.entries),
        (entry.username for entry in latest.entries),
    )


@main_bp.route("/accounts/<int:account_id>/upload", methods=["POST"])
@login_required
def upload_snapshot(account_id: int):
    account = _get_account_or_404(account_id)
    file = request.files.get("snapshot_file")
    snapshot_type_raw = request.form.get("snapshot_type", "")

    try:
        snapshot_type = validate_snapshot_type(snapshot_type_raw)
    except ValidationError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("main.view_account", account_id=account.id))

    if not file or file.filename == "":
        flash("Please select a CSV export to upload.", "danger")
        return redirect(url_for("main.view_account", account_id=account.id))

    rows = parse_snapshot_file(file.stream)
    if not rows:
        flash("No rows were found in the uploaded file.", "warning")
        return redirect(url_for("main.view_account", account_id=account.id))

    snapshot = Snapshot(tracked_account_id=account.id, snapshot_type=snapshot_type)
    db.session.add(snapshot)
    db.session.flush()

    usernames = []
    for username, full_name in rows:
        entry = SnapshotEntry(snapshot_id=snapshot.id, username=username, full_name=full_name)
        db.session.add(entry)
        usernames.append(username)

    db.session.commit()
    flash(
        f"Snapshot stored with {len(usernames)} entries. We'll compare it to previous uploads.",
        "success",
    )
    return redirect(url_for("main.view_account", account_id=account.id))


@main_bp.route("/accounts/<int:account_id>/export", methods=["POST"])
@login_required
def export_snapshot(account_id: int):
    account = _get_account_or_404(account_id)
    snapshot_type_raw = request.form.get("snapshot_type", "")
    export_format_raw = request.form.get("export_format", "csv")
    expects_json = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    try:
        snapshot_type = validate_snapshot_type(snapshot_type_raw)
        export_format = validate_export_format(export_format_raw)
    except ValidationError as exc:
        if expects_json:
            return jsonify({"status": "error", "message": str(exc)}), 400
        flash(str(exc), "danger")
        return redirect(url_for("main.view_account", account_id=account.id))

    latest_snapshot = account.latest_snapshot(snapshot_type)
    if not latest_snapshot:
        message = "Upload a snapshot before exporting."
        if expects_json:
            return jsonify({"status": "error", "message": message}), 400
        flash(message, "warning")
        return redirect(url_for("main.view_account", account_id=account.id))

    data = _snapshot_entries(latest_snapshot)
    if exceeds_free_limit(len(data)) and not current_user.is_subscribed:
        message = "Upgrade required to export more than 600 profiles."
        if expects_json:
            return jsonify({"status": "redirect", "url": url_for("main.paywall")}), 402
        flash(message, "danger")
        return redirect(url_for("main.paywall"))

    if expects_json:
        token = _create_export_token(latest_snapshot, export_format)
        download_url = url_for(
            "main.export_snapshot_download",
            account_id=account.id,
            token=token,
        )
        return jsonify({"status": "ok", "download_url": download_url})

    if export_format == "csv":
        return _export_csv(account, snapshot_type, data)
    return _export_excel(account, snapshot_type, data)


@main_bp.route("/accounts/<int:account_id>/export/download")
@login_required
def export_snapshot_download(account_id: int):
    token = request.args.get("token", "")
    if not token:
        abort(400)

    serializer = _export_serializer()
    try:
        payload = serializer.loads(token, max_age=300)
    except BadSignature:
        abort(400)

    if payload.get("account_id") != account_id:
        abort(403)

    account = _get_account_or_404(account_id)
    snapshot_id = payload.get("snapshot_id")
    snapshot_type = payload.get("snapshot_type")
    export_format = payload.get("format", "csv")

    snapshot = Snapshot.query.filter_by(
        id=snapshot_id, tracked_account_id=account.id, snapshot_type=snapshot_type
    ).first()
    if not snapshot:
        abort(404)

    data = _snapshot_entries(snapshot)
    if exceeds_free_limit(len(data)) and not current_user.is_subscribed:
        flash("Upgrade required to export more than 600 profiles.", "danger")
        return redirect(url_for("main.paywall"))

    if export_format == "csv":
        return _export_csv(account, snapshot_type, data)
    return _export_excel(account, snapshot_type, data)


def _snapshot_entries(snapshot: Snapshot) -> list[dict[str, Optional[str]]]:
    return [
        {"username": entry.username, "full_name": entry.full_name or ""}
        for entry in snapshot.entries
    ]


def _create_export_token(snapshot: Snapshot, export_format: str) -> str:
    serializer = _export_serializer()
    payload = {
        "account_id": snapshot.tracked_account_id,
        "snapshot_id": snapshot.id,
        "snapshot_type": snapshot.snapshot_type,
        "format": export_format,
    }
    return serializer.dumps(payload)


def _export_serializer() -> URLSafeTimedSerializer:
    secret_key = current_app.config.get("SECRET_KEY")
    if not secret_key:  # pragma: no cover - Flask always requires a secret key
        raise RuntimeError("SECRET_KEY is required for export signing")
    salt = current_app.config.get("EXPORT_SALT", "igfollow.export")
    return URLSafeTimedSerializer(secret_key, salt=salt)


def _export_csv(account: TrackedAccount, snapshot_type: str, data: Iterable[dict[str, str]]):
    import csv

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["username", "full_name"])
    writer.writeheader()
    for row in data:
        writer.writerow(row)

    filename = _export_filename(account.instagram_username, snapshot_type, "csv")
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def _export_excel(account: TrackedAccount, snapshot_type: str, data: Iterable[dict[str, str]]):
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = f"{snapshot_type.title()}"
    sheet.append(["username", "full_name"])
    for row in data:
        sheet.append([row["username"], row["full_name"]])

    stream = io.BytesIO()
    workbook.save(stream)
    stream.seek(0)

    filename = _export_filename(account.instagram_username, snapshot_type, "xlsx")
    return send_file(
        stream,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _export_filename(username: str, snapshot_type: str, extension: str) -> str:
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    return f"{username}-{snapshot_type}-{timestamp}.{extension}"


@main_bp.route("/paywall")
@login_required
def paywall():
    return render_template("paywall.html")


def _get_account_or_404(account_id: int) -> TrackedAccount:
    account = TrackedAccount.query.filter_by(id=account_id, user_id=current_user.id).first()
    if not account:
        abort(404)
    return account
