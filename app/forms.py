from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import json
from typing import Iterable, Optional
from urllib.parse import urlparse

from werkzeug.datastructures import FileStorage


@dataclass
class SnapshotUploadResult:
    total: int
    added: Iterable[str]
    removed: Iterable[str]
    snapshot_type: str


class ValidationError(Exception):
    pass


def validate_snapshot_type(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"followers", "following"}:
        raise ValidationError("Snapshot type must be either 'followers' or 'following'.")
    return normalized


def validate_export_format(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"csv", "xlsx"}:
        raise ValidationError("Format must be CSV or XLSX.")
    return normalized


def normalize_username(username: str) -> str:
    cleaned = (username or "").strip().lstrip("@")
    return cleaned.lower()


def parse_snapshot_file(file: FileStorage) -> list[tuple[str, Optional[str]]]:
    """Parse an uploaded Instagram export file into (username, full_name) pairs."""
    import csv
    import io

    raw = file.read()
    if not raw:
        return []
    if isinstance(raw, bytes):
        text = raw.decode("utf-8-sig")
    else:
        text = raw

    # Reset pointer so the caller can re-read if needed (useful in tests)
    try:
        file.stream.seek(0)
    except Exception:  # pragma: no cover - FileStorage may not support seek in some contexts
        pass

    stripped = text.strip()
    filename = (file.filename or "").lower()

    rows: list[tuple[str, Optional[str]]] = []

    if _looks_like_json(filename, stripped):
        rows = _parse_json_export(stripped)

    if not rows and _looks_like_csv(filename, stripped):
        rows = _parse_csv_export(csv, io, stripped)

    if not rows:
        rows = _parse_plain_list(stripped)

    unique: "OrderedDict[str, tuple[str, Optional[str]]]" = OrderedDict()
    for username, full_name in rows:
        normalized = normalize_username(username)
        if not normalized:
            continue
        key = normalized
        if key not in unique:
            unique[key] = (normalized, full_name.strip() if full_name else None)
    return list(unique.values())


def _looks_like_json(filename: str, contents: str) -> bool:
    return filename.endswith(".json") or contents.startswith("[") or contents.startswith("{")


def _looks_like_csv(filename: str, contents: str) -> bool:
    if filename.endswith(".csv"):
        return True
    header = contents.splitlines()[0]
    return "," in header or ";" in header


def _parse_csv_export(csv_module, io_module, contents: str) -> list[tuple[str, Optional[str]]]:
    delimiter = ";" if ";" in contents.splitlines()[0] and "," not in contents.splitlines()[0] else ","
    reader = csv_module.DictReader(io_module.StringIO(contents), delimiter=delimiter)
    rows: list[tuple[str, Optional[str]]] = []
    if reader.fieldnames:
        for row in reader:
            username = (
                row.get("username")
                or row.get("handle")
                or row.get("user")
                or row.get("profile url")
                or row.get("profile")
            )
            full_name = row.get("full_name") or row.get("name") or row.get("title")
            if username:
                rows.append((username, full_name))
    else:
        reader = csv_module.reader(io_module.StringIO(contents), delimiter=delimiter)
        for row in reader:
            if not row:
                continue
            username = row[0]
            full_name = row[1] if len(row) > 1 else None
            rows.append((username, full_name))
    return rows


def _parse_plain_list(contents: str) -> list[tuple[str, Optional[str]]]:
    rows: list[tuple[str, Optional[str]]] = []
    for line in contents.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        if "," in cleaned:
            username, _, full_name = cleaned.partition(",")
            rows.append((username, full_name))
        elif " - " in cleaned:
            username, _, full_name = cleaned.partition(" - ")
            rows.append((username, full_name))
        else:
            rows.append((cleaned, None))
    return rows


def _parse_json_export(contents: str) -> list[tuple[str, Optional[str]]]:
    try:
        payload = json.loads(contents)
    except json.JSONDecodeError:
        return []

    entries: list[tuple[str, Optional[str]]] = []
    seen = set()

    def extract(obj, context_name: Optional[str] = None):
        if isinstance(obj, dict):
            if "string_list_data" in obj and isinstance(obj["string_list_data"], list):
                display_name = obj.get("title") or obj.get("name") or context_name
                for item in obj["string_list_data"]:
                    username = item.get("value") or _username_from_href(item.get("href"))
                    full_name = display_name or item.get("title") or item.get("name")
                    if username:
                        key = (username, full_name)
                        if key not in seen:
                            entries.append((username, full_name))
                            seen.add(key)
                return

            if "username" in obj:
                username = obj.get("username")
                full_name = obj.get("full_name") or obj.get("name")
                key = (username, full_name)
                if username and key not in seen:
                    entries.append((username, full_name))
                    seen.add(key)

            if "value" in obj and not isinstance(obj["value"], (dict, list)):
                username = obj.get("value")
                full_name = obj.get("title") or obj.get("name") or context_name
                key = (username, full_name)
                if username and key not in seen:
                    entries.append((username, full_name))
                    seen.add(key)

            for key_name, value in obj.items():
                if key_name == "string_list_data":
                    continue
                if isinstance(value, (list, dict)):
                    extract(value, obj.get("title") or context_name)

        elif isinstance(obj, list):
            for item in obj:
                extract(item, context_name)

    extract(payload)
    return entries


def _username_from_href(href: Optional[str]) -> Optional[str]:
    if not href:
        return None
    parsed = urlparse(href)
    path = (parsed.path or "").strip("/")
    if not path:
        return None
    return path.split("/", 1)[0]
