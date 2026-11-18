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
