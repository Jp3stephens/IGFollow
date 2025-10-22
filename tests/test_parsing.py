import io

from werkzeug.datastructures import FileStorage

from app.forms import parse_snapshot_file


def make_file(contents: str, filename: str) -> FileStorage:
    return FileStorage(stream=io.BytesIO(contents.encode("utf-8")), filename=filename)


def test_parse_csv_export_handles_common_headers():
    file = make_file("username,full_name\nalice,Alice\nBob,", "followers.csv")
    rows = parse_snapshot_file(file)
    assert rows == [("alice", "Alice"), ("bob", None)]


def test_parse_json_string_list_data():
    payload = """
    [
      {
        "title": "Alice",
        "string_list_data": [
          {"value": "alice", "href": "https://www.instagram.com/alice/"}
        ]
      },
      {
        "string_list_data": [
          {"value": "bob"}
        ]
      }
    ]
    """
    file = make_file(payload, "followers.json")
    rows = parse_snapshot_file(file)
    assert ("alice", "Alice") in rows
    assert ("bob", None) in rows


def test_parse_plain_text_list():
    file = make_file("carol\n@dave\n", "followers.txt")
    rows = parse_snapshot_file(file)
    assert rows == [("carol", None), ("dave", None)]
