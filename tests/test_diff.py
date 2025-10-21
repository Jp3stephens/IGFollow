from app.diff import compute_diff


def test_compute_diff_handles_new_and_removed_entries():
    previous = ["alice", "Bob", "charlie"]
    current = ["bob", "charlie", "diana", "eve"]

    diff = compute_diff(previous, current)

    assert diff.added == ["diana", "eve"]
    assert diff.removed == ["alice"]


def test_compute_diff_with_empty_inputs():
    diff = compute_diff([], [])
    assert diff.added == []
    assert diff.removed == []
