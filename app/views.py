from __future__ import annotations

import io
from datetime import datetime, timedelta
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
from .instagram import InstagramServiceError, get_instagram_service
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
    service = get_instagram_service()
    return render_template(
        "dashboard.html",
        accounts=accounts,
        instagram_connected=service.is_connected(current_user),
        instagram_available=service.is_available(),
        instagram_error=service.availability_error(),
    )


@main_bp.route("/settings/instagram", methods=["GET", "POST"])
@login_required
def instagram_settings():
    service = get_instagram_service()
    if request.method == "POST":
        action = request.form.get("action", "connect")
        if action == "disconnect":
            service.disconnect_user(current_user)
            flash("Instagram account disconnected.", "info")
            return redirect(url_for("main.instagram_settings"))

        username = request.form.get("instagram_username", "")
        password = request.form.get("instagram_password", "")
        try:
            service.connect_user(current_user, username, password)
        except InstagramServiceError as exc:
            flash(str(exc), "danger")
        else:
            flash("Instagram account connected successfully.", "success")
        return redirect(url_for("main.instagram_settings"))

    session = current_user.instagram_session
    return render_template(
        "settings/instagram.html",
        instagram_session=session,
        instagram_connected=service.is_connected(current_user),
        instagram_available=service.is_available(),
        instagram_error=service.availability_error(),
    )


@main_bp.route("/accounts/add", methods=["GET", "POST"])
@login_required
def add_account():
    service = get_instagram_service()
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

            try:
                refreshed = _ensure_instagram_snapshots(account, user=current_user, force=True)
            except InstagramServiceError as exc:
                flash(str(exc), "danger")
                flash(
                    "Account added, but we could not reach Instagram. You can upload a snapshot manually while credentials are fixed.",
                    "warning",
                )
            else:
                if refreshed:
                    flash("Account added and synced with Instagram.", "success")
                elif service.is_connected(current_user):
                    flash("Account added. We'll keep checking Instagram for updates.", "success")
                else:
                    flash(
                        "Account added. Connect Instagram credentials to enable automatic syncing, or upload snapshots manually.",
                        "info",
                    )
            return redirect(url_for("main.view_account", account_id=account.id))

    return render_template(
        "accounts/add.html",
        instagram_connected=service.is_connected(current_user),
        instagram_available=service.is_available(),
        instagram_error=service.availability_error(),
    )


@main_bp.route("/accounts/<int:account_id>")
@login_required
def view_account(account_id: int):
    account = _get_account_or_404(account_id)
    try:
        _ensure_instagram_snapshots(account, user=current_user)
    except InstagramServiceError as exc:
        flash(str(exc), "warning")
    followers_snapshot = account.latest_snapshot("followers")
    following_snapshot = account.latest_snapshot("following")
    followers = _latest_diff(account, "followers")
    following = _latest_diff(account, "following")
    service = get_instagram_service()
    return render_template(
        "accounts/detail.html",
        account=account,
        followers_diff=followers,
        following_diff=following,
        followers_snapshot=followers_snapshot,
        following_snapshot=following_snapshot,
        followers_entries=_snapshot_entries(followers_snapshot) if followers_snapshot else [],
        following_entries=_snapshot_entries(following_snapshot) if following_snapshot else [],
        instagram_connected=service.is_connected(current_user),
        instagram_available=service.is_available(),
        instagram_error=service.availability_error(),
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


def _normalize_username(value: str) -> str:
    return value.strip().lstrip("@").lower()


def _prepare_entries(rows: Iterable[tuple[str, Optional[str]]], user) -> list[dict[str, str]]:
    service = get_instagram_service()
    prepared: dict[str, dict[str, str]] = {}
    for username, full_name in rows:
        normalized = _normalize_username(username or "")
        if not normalized:
            continue
        if normalized in prepared:
            continue

        resolved_name = (full_name or "").strip()
        profile_pic_url = ""

        if user and service.is_connected(user):
            try:
                profile = service.fetch_profile(user, normalized)
            except InstagramServiceError:
                profile = None
            if profile:
                resolved_name = resolved_name or profile["full_name"]
                profile_pic_url = profile["profile_pic_url"]

        prepared[normalized] = {
            "username": normalized,
            "full_name": resolved_name,
            "profile_pic_url": profile_pic_url,
        }

    return list(prepared.values())


def _store_snapshot(
    account: TrackedAccount,
    snapshot_type: str,
    entries: Iterable[dict[str, str]],
    *,
    commit: bool = True,
) -> tuple[Snapshot, SnapshotDiff]:
    previous_snapshot = account.latest_snapshot(snapshot_type)

    snapshot = Snapshot(tracked_account_id=account.id, snapshot_type=snapshot_type)
    db.session.add(snapshot)
    db.session.flush()

    seen: set[str] = set()
    usernames: list[str] = []
    for entry in entries:
        username = _normalize_username(entry.get("username", ""))
        if not username or username in seen:
            continue
        seen.add(username)
        full_name = (entry.get("full_name") or "").strip()
        profile_pic_url = entry.get("profile_pic_url") or ""
        db.session.add(
            SnapshotEntry(
                snapshot_id=snapshot.id,
                username=username,
                full_name=full_name,
                profile_pic_url=profile_pic_url,
            )
        )
        usernames.append(username)

    if previous_snapshot:
        previous_usernames = [entry.username for entry in previous_snapshot.entries]
        diff = compute_diff(previous_usernames, usernames)
    else:
        diff = SnapshotDiff(added=usernames, removed=[])

    if commit:
        db.session.commit()

    return snapshot, diff


def _ensure_instagram_snapshots(
    account: TrackedAccount,
    *,
    user,
    snapshot_type: Optional[str] = None,
    force: bool = False,
) -> bool:
    service = get_instagram_service()
    if not service.is_available():
        current_app.logger.info(
            "Instagram service is unavailable; skipping automatic sync for %s",
            account.instagram_username,
        )
        return False

    if not user or not service.is_connected(user):
        current_app.logger.info(
            "Instagram service is not configured; skipping automatic sync for %s",
            account.instagram_username,
        )
        return False

    profile = service.fetch_profile(user, account.instagram_username)
    account.instagram_username = profile["username"]
    account.instagram_user_id = profile["user_id"]
    if profile.get("profile_pic_url"):
        account.profile_picture_url = profile["profile_pic_url"]

    db.session.add(account)
    db.session.flush()

    cache_minutes = int(current_app.config.get("INSTAGRAM_CACHE_MINUTES", 10))
    freshness_threshold = datetime.utcnow() - timedelta(minutes=cache_minutes)

    snapshot_types = [snapshot_type] if snapshot_type else ["followers", "following"]
    refreshed = False

    for entry_type in snapshot_types:
        latest = account.latest_snapshot(entry_type)
        if not force and latest and latest.created_at >= freshness_threshold:
            continue

        relationships = service.fetch_relationships(user, profile["user_id"], entry_type)
        entries = [
            {
                "username": rel["username"],
                "full_name": rel["full_name"],
                "profile_pic_url": rel["profile_pic_url"],
            }
            for rel in relationships
        ]
        _store_snapshot(account, entry_type, entries, commit=False)
        refreshed = True

    db.session.commit()
    return refreshed


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

    rows = parse_snapshot_file(file)
    if not rows:
        flash("No rows were found in the uploaded file.", "warning")
        return redirect(url_for("main.view_account", account_id=account.id))

    entries = _prepare_entries(rows, current_user)
    snapshot, diff = _store_snapshot(account, snapshot_type, entries)

    if diff.removed or diff.added:
        flash(
            "Snapshot stored. Added {added} new and lost {removed} compared to the previous upload.".format(
                added=len(diff.added), removed=len(diff.removed)
            ),
            "success",
        )
    else:
        flash(
            f"Snapshot stored with {len(entries)} entries. We'll compare it to future uploads.",
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

    try:
        _ensure_instagram_snapshots(account, user=current_user, snapshot_type=snapshot_type)
    except InstagramServiceError as exc:
        if expects_json:
            return jsonify({"status": "error", "message": str(exc)}), 502
        flash(str(exc), "danger")
        return redirect(url_for("main.view_account", account_id=account.id))

    latest_snapshot = account.latest_snapshot(snapshot_type)
    if not latest_snapshot:
        message = "We could not find any data for this list yet. Upload a snapshot or check your Instagram credentials."
        if expects_json:
            return jsonify({"status": "error", "message": message}), 400
        flash(message, "warning")
        return redirect(url_for("main.view_account", account_id=account.id))

    export_limit = None
    message = None
    total_rows = len(latest_snapshot.entries)
    max_free = current_app.config.get("MAX_FREE_EXPORT", 600)
    if not current_user.is_subscribed and total_rows > max_free:
        export_limit = max_free
        message = (
            f"Free plan exports include the first {max_free:,} profiles. Upgrade to download all {total_rows:,}."
        )

    data = _snapshot_entries(latest_snapshot, limit=export_limit)

    if export_limit and not expects_json and message:
        flash(message, "warning")

    if expects_json:
        token = _create_export_token(latest_snapshot, export_format, limit=export_limit)
        download_url = url_for(
            "main.export_snapshot_download",
            account_id=account.id,
            token=token,
        )
        payload = {"status": "ok", "download_url": download_url}
        if export_limit:
            payload.update(
                {
                    "limited": True,
                    "total_rows": total_rows,
                    "exported_rows": len(data),
                    "message": message,
                }
            )
        return jsonify(payload)

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
    limit = payload.get("limit")

    snapshot = Snapshot.query.filter_by(
        id=snapshot_id, tracked_account_id=account.id, snapshot_type=snapshot_type
    ).first()
    if not snapshot:
        abort(404)

    data = _snapshot_entries(snapshot, limit=limit)
    if limit and exceeds_free_limit(len(snapshot.entries)) and not current_user.is_subscribed:
        flash(
            f"Free plan exports include the first {limit:,} profiles. Upgrade for full downloads.",
            "warning",
        )

    if export_format == "csv":
        return _export_csv(account, snapshot_type, data)
    return _export_excel(account, snapshot_type, data)


def _snapshot_entries(
    snapshot: Optional[Snapshot], limit: Optional[int] = None
) -> list[dict[str, Optional[str]]]:
    if not snapshot:
        return []

    entries = sorted(
        snapshot.entries,
        key=lambda entry: (entry.username or "").lower(),
    )

    if limit is not None:
        entries = entries[:limit]

    results: list[dict[str, Optional[str]]] = []
    for entry in entries:
        username = entry.username
        avatar_url = entry.profile_pic_url or _avatar_url(username)
        results.append(
            {
                "username": username,
                "full_name": entry.full_name or "",
                "avatar_url": avatar_url,
            }
        )
    return results


def _create_export_token(
    snapshot: Snapshot, export_format: str, limit: Optional[int] = None
) -> str:
    serializer = _export_serializer()
    payload = {
        "account_id": snapshot.tracked_account_id,
        "snapshot_id": snapshot.id,
        "snapshot_type": snapshot.snapshot_type,
        "format": export_format,
    }
    if limit is not None:
        payload["limit"] = limit
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
        writer.writerow({"username": row.get("username", ""), "full_name": row.get("full_name", "")})

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
        sheet.append([row.get("username", ""), row.get("full_name", "")])

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


def _avatar_url(username: str) -> str:
    safe_username = (username or "").strip()
    if not safe_username:
        return ""
    return f"https://unavatar.io/instagram/{safe_username}"


@main_bp.route("/paywall")
@login_required
def paywall():
    return render_template("paywall.html")


def _get_account_or_404(account_id: int) -> TrackedAccount:
    account = TrackedAccount.query.filter_by(id=account_id, user_id=current_user.id).first()
    if not account:
        abort(404)
    return account
