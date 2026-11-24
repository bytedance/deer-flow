"""Skill history records use physical JSONL boundaries, not Unicode text lines."""

import json

import pytest


@pytest.fixture(params=["local", "user"])
def storage(request, monkeypatch, tmp_path):
    from deerflow.config.paths import Paths
    from deerflow.skills.storage.local_skill_storage import LocalSkillStorage
    from deerflow.skills.storage.user_scoped_skill_storage import UserScopedSkillStorage

    root = tmp_path / "skills"
    if request.param == "local":
        return LocalSkillStorage(host_path=str(root))
    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: Paths(base_dir=tmp_path))
    return UserScopedSkillStorage("history-owner", host_path=str(root))


@pytest.mark.parametrize("separator", ["\u0085", "\u2028", "\u2029"])
@pytest.mark.parametrize("field", ["prev_content", "new_content", "reason"])
def test_append_read_round_trip_preserves_unicode_separators(storage, separator, field):
    records = [{"action": "create", "new_content": "first"}, {"action": "human_edit", field: f"before{separator}after"}, {"action": "human_edit", "reason": "last"}]
    for record in records:
        storage.append_history("demo-skill", record)

    # The real writer leaves the separator inside a valid JSON string.
    raw = storage.get_skill_history_file("demo-skill").read_bytes().decode("utf-8")
    assert separator in raw
    assert len([json.loads(line) for line in raw.split("\n") if line.strip()]) == 3
    actual = storage.read_history("demo-skill")
    assert [{key: value for key, value in record.items() if key != "ts"} for record in actual] == records
    assert all(record["ts"] for record in actual)


@pytest.mark.parametrize("ending", ["\n", "\r\n"])
def test_physical_lines_keep_blank_lines_and_unterminated_final_record(storage, ending):
    path = storage.get_skill_history_file("demo-skill")
    path.parent.mkdir(parents=True)
    records = [{"new_content": "first\nsecond"}, {"reason": "last"}]
    content = ending + " \t" + ending + ending.join(json.dumps(record) for record in records)
    path.write_bytes(content.encode("utf-8"))
    assert storage.read_history("demo-skill") == records


def test_missing_history_keeps_empty_result(storage):
    assert storage.read_history("demo-skill") == []


def test_malformed_json_is_still_rejected(storage):
    path = storage.get_skill_history_file("demo-skill")
    path.parent.mkdir(parents=True)
    path.write_bytes(b'{"reason":"valid"}\n{"reason":')
    with pytest.raises(json.JSONDecodeError):
        storage.read_history("demo-skill")


def test_concurrent_appends_keep_one_record_per_line(storage):
    # Records this large hold two SKILL.md revisions; they outgrow the text-file
    # buffer, which once sent the "\n" terminator in a separate write.
    import threading

    bodies = {tag: tag * 65536 for tag in "abcd"}

    def append(tag):
        for index in range(40):
            storage.append_history("demo-skill", {"action": "edit", "author": tag, "index": index, "new_content": bodies[tag]})

    threads = [threading.Thread(target=append, args=(tag,)) for tag in bodies]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    records = storage.read_history("demo-skill")
    assert sorted((record["author"], record["index"]) for record in records) == sorted((tag, index) for tag in bodies for index in range(40))
    assert all(record["new_content"] == bodies[record["author"]] for record in records)


def _history_writes(monkeypatch, storage, *, first_write_limit=None):
    """Record every ``os.write`` to the history file, optionally shortening the first."""
    import os

    history_path = storage.get_skill_history_file("demo-skill")
    real_write = os.write
    writes = []

    def is_history(fd):
        try:
            target = os.stat(history_path)
        except FileNotFoundError:
            return False
        opened = os.fstat(fd)
        return (opened.st_dev, opened.st_ino) == (target.st_dev, target.st_ino)

    def write(fd, data):
        if not is_history(fd):
            return real_write(fd, data)
        data = bytes(data)
        if first_write_limit is not None and not writes:
            data = data[:first_write_limit]
        writes.append(data)
        return real_write(fd, data)

    monkeypatch.setattr(os, "write", write)
    return writes


def test_each_record_reaches_the_file_in_one_write(storage, monkeypatch):
    writes = _history_writes(monkeypatch, storage)

    storage.append_history("demo-skill", {"action": "edit", "new_content": "x" * 65536})
    storage.append_history("demo-skill", {"action": "edit", "reason": "small"})

    assert len(writes) == 2
    assert all(data.endswith(b"\n") and data.count(b"\n") == 1 for data in writes)
    assert [record["action"] for record in storage.read_history("demo-skill")] == ["edit", "edit"]


def test_a_short_write_still_stores_the_whole_record(storage, monkeypatch):
    writes = _history_writes(monkeypatch, storage, first_write_limit=10)

    storage.append_history("demo-skill", {"action": "edit", "new_content": "x" * 1000})

    assert len(writes) == 2 and len(writes[0]) == 10
    (record,) = storage.read_history("demo-skill")
    assert record["new_content"] == "x" * 1000
