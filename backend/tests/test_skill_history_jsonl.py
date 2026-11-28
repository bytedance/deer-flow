"""Skill history records use physical JSONL boundaries, not Unicode text lines."""

import json
import os

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


def _script_history_writes(monkeypatch, storage, script=None):
    """Route every ``os.write`` to the history file through ``script``.

    ``script(data, write)`` performs the write with ``write`` and returns its
    count; it may shorten ``data`` or let another writer run around it. Returns
    the list of bytes that reached the file, one entry per write.
    """
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

        def record(chunk):
            writes.append(bytes(chunk))
            return real_write(fd, chunk)

        return script(bytes(data), record) if script is not None else record(data)

    monkeypatch.setattr(os, "write", write)
    return writes


def _shorten_first_write(limit, before_rest=None):
    """Cut the first write to ``limit`` bytes; run ``before_rest`` before the retry."""
    calls = []

    def script(data, write):
        calls.append(data)
        if len(calls) == 1:
            return write(data[:limit])
        if len(calls) == 2 and before_rest is not None:
            before_rest()
        return write(data)

    return script


def _signal_blocked_history_lock(monkeypatch):
    """Set the returned event when a storage read or append has to wait for the history file lock.

    The holder of a short write uses it as a barrier: it retries only once the
    other thread is blocked on the lock, or has finished without waiting for
    it, which is past the point where a path that is not excluded would have
    touched the file. Neither depends on how the threads are scheduled.
    """
    import threading

    from deerflow.skills.storage import local_skill_storage

    blocked = threading.Event()
    real = local_skill_storage.locked_history_file

    def held_elsewhere(fd):
        try:
            import fcntl
        except ImportError:  # Windows
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            except OSError:
                return True
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            return False
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False

    def locked(fd, **kwargs):
        if held_elsewhere(fd):
            blocked.set()
        return real(fd, **kwargs)

    monkeypatch.setattr(local_skill_storage, "locked_history_file", locked)
    return blocked


def _thread_signalling(event, target, *args):
    """A thread running ``target`` that also sets ``event`` when it ends."""
    import threading

    def run():
        try:
            target(*args)
        finally:
            event.set()

    return threading.Thread(target=run)


def _operation(operation_id):
    from deerflow_extension_api.skill_mutations import AssetRevision, Operation

    revision = AssetRevision("incarnation", 1, "digest")
    return Operation(operation_id, "history-owner", "demo-skill", "published", "main", revision, revision, 1)


def test_each_record_reaches_the_file_in_one_write(storage, monkeypatch):
    writes = _script_history_writes(monkeypatch, storage)

    storage.append_history("demo-skill", {"action": "edit", "new_content": "x" * 65536})
    storage.append_history("demo-skill", {"action": "edit", "reason": "small"})

    assert len(writes) == 2
    assert all(data.endswith(b"\n") and data.count(b"\n") == 1 for data in writes)
    assert [record["action"] for record in storage.read_history("demo-skill")] == ["edit", "edit"]


def test_a_short_write_still_stores_the_whole_record(storage, monkeypatch):
    writes = _script_history_writes(monkeypatch, storage, _shorten_first_write(10))

    storage.append_history("demo-skill", {"action": "edit", "new_content": "x" * 1000})

    assert len(writes) == 2 and len(writes[0]) == 10
    (record,) = storage.read_history("demo-skill")
    assert record["new_content"] == "x" * 1000


def test_another_append_waits_for_a_short_write_to_finish(storage, monkeypatch):
    blocked = _signal_blocked_history_lock(monkeypatch)
    other = _thread_signalling(blocked, storage.append_history, "demo-skill", {"action": "edit", "author": "b"})

    def let_the_other_append_run():
        # Between the short write and its retry: the record is half written.
        # The retry waits until the other append is blocked on the lock, or
        # has finished without waiting.
        other.start()
        assert blocked.wait(timeout=5)

    _script_history_writes(monkeypatch, storage, _shorten_first_write(10, before_rest=let_the_other_append_run))

    storage.append_history("demo-skill", {"action": "edit", "author": "a", "new_content": "x" * 1000})
    other.join(timeout=5)

    assert not other.is_alive()
    assert [record["author"] for record in storage.read_history("demo-skill")] == ["a", "b"]


def test_a_read_waits_for_a_short_write_to_finish(storage, monkeypatch):
    storage.append_history("demo-skill", {"action": "create", "author": "first"})
    blocked = _signal_blocked_history_lock(monkeypatch)
    seen = []

    def read():
        try:
            seen.append([record["author"] for record in storage.read_history("demo-skill")])
        except json.JSONDecodeError as error:
            seen.append(error)

    reader = _thread_signalling(blocked, read)

    def let_the_read_run():
        # Between the short write and its retry: the tail is half a record.
        # The retry waits until the reader is blocked on the lock, or has read
        # without waiting.
        reader.start()
        assert blocked.wait(timeout=5)

    _script_history_writes(monkeypatch, storage, _shorten_first_write(10, before_rest=let_the_read_run))

    storage.append_history("demo-skill", {"action": "edit", "author": "a", "new_content": "x" * 1000})
    reader.join(timeout=5)

    assert not reader.is_alive()
    assert seen == [["first", "a"]]


@pytest.mark.skipif(os.name != "posix", reason="msvcrt.locking has no shared mode, so Windows readers lock exclusively")
def test_reads_share_the_history_lock(storage):
    import fcntl
    import threading

    storage.append_history("demo-skill", {"action": "create", "author": "first"})
    seen = []
    with storage.get_skill_history_file("demo-skill").open("rb") as other_reader:
        fcntl.flock(other_reader, fcntl.LOCK_SH)
        reader = threading.Thread(target=lambda: seen.append(storage.read_history("demo-skill")))
        reader.start()
        reader.join(timeout=5)
        fcntl.flock(other_reader, fcntl.LOCK_UN)

    assert not reader.is_alive()
    assert [record["author"] for record in seen[0]] == ["first"]


@pytest.mark.skipif(os.name != "posix", reason="the operation mirror requires POSIX directory descriptors")
def test_the_operation_mirror_and_appends_share_the_history_lock(storage, monkeypatch):
    import threading

    from deerflow.skills.mutations.history import mirror_operations

    storage.get_skill_history_file("demo-skill").parent.mkdir(parents=True)
    # Set when the append has to wait for the mirror's lock, or, without that
    # lock, once the append's first, short write is in.
    append_held = _signal_blocked_history_lock(monkeypatch)
    resume_append = threading.Event()
    append = threading.Thread(target=storage.append_history, args=("demo-skill", {"action": "edit", "author": "a"}))
    append_calls = []

    def script(data, write):
        if b'"operation_id":"op-b"' in data:
            # The mirror is about to write. An append that starts now must not
            # get its first, short write in before the mirror's record.
            append.start()
            assert append_held.wait(timeout=5)
            written = write(data)
            resume_append.set()
            return written
        append_calls.append(data)
        if len(append_calls) > 1:
            return write(data)
        written = write(data[:10])
        append_held.set()
        resume_append.wait(timeout=5)
        return written

    _script_history_writes(monkeypatch, storage, script)

    mirror_operations(storage, [_operation("op-b")])
    append.join(timeout=5)

    assert not append.is_alive()
    assert [record.get("operation_id", record.get("author")) for record in storage.read_history("demo-skill")] == ["op-b", "a"]
