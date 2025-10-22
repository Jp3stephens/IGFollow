from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional


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
    return username.strip()


def parse_snapshot_file(file_stream) -> list[tuple[str, Optional[str]]]:
    """Parse uploaded CSV file. Expect headers username,full_name"""
    import csv
    import io

    decoded = file_stream.read()
    if isinstance(decoded, bytes):
        decoded = decoded.decode("utf-8-sig")

    reader = csv.DictReader(io.StringIO(decoded))
    rows: list[tuple[str, Optional[str]]] = []
    for row in reader:
        username = row.get("username") or row.get("handle") or row.get("user")
        full_name = row.get("full_name") or row.get("name")
        if username:
            rows.append((normalize_username(username), full_name.strip() if full_name else None))
    return rows
