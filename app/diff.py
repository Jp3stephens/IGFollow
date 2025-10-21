from collections.abc import Iterable
from dataclasses import dataclass
from typing import List, Set


@dataclass
class SnapshotDiff:
    added: List[str]
    removed: List[str]


def compute_diff(old: Iterable[str], new: Iterable[str]) -> SnapshotDiff:
    old_set: Set[str] = {item.strip().lower() for item in old if item}
    new_set: Set[str] = {item.strip().lower() for item in new if item}
    added = sorted(new_set - old_set)
    removed = sorted(old_set - new_set)
    return SnapshotDiff(added=added, removed=removed)
