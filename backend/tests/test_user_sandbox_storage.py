import pytest

from deerflow.config.paths import Paths


def test_migration_preserves_files_and_separates_private_thread_metadata(tmp_path):
    from deerflow.community.aio_sandbox.user_storage import migrate_user_data

    old = Paths(tmp_path)
    old.ensure_thread_dirs("chat-a", user_id="alice")
    old.ensure_thread_dirs("chat-b", user_id="bob")
    (old.sandbox_outputs_dir("chat-a", user_id="alice") / "report.txt").write_text("keep me", encoding="utf-8")
    metadata = old.thread_dir("chat-a", user_id="alice") / "private.json"
    metadata.write_text("private", encoding="utf-8")
    migrate_user_data(tmp_path)
    current = Paths(tmp_path)
    current.ensure_thread_dirs("new-chat", user_id="alice")
    assert current.thread_dir("new-chat", user_id="alice").is_dir()
    assert (current.sandbox_outputs_dir("chat-a", user_id="alice") / "report.txt").read_text(encoding="utf-8") == "keep me"
    assert current.sandbox_user_data_dir("chat-a", user_id="alice") == tmp_path / "users/alice/sandbox-data/chat-a"
    assert metadata.read_text(encoding="utf-8") == "private"
    assert not (tmp_path / "users/alice/sandbox-data/chat-a/private.json").exists()
    migrate_user_data(tmp_path)
    current.delete_thread_dir("chat-a", user_id="alice")
    assert not current.sandbox_user_data_dir("chat-a", user_id="alice").exists()
    assert current.sandbox_user_data_dir("chat-b", user_id="bob").is_dir()


def test_migration_fails_without_overwriting_conflicting_destination(tmp_path):
    from deerflow.community.aio_sandbox.user_storage import migrate_user_data

    old = Paths(tmp_path)
    old.ensure_thread_dirs("chat-a", user_id="alice")
    conflict = tmp_path / "users/alice/sandbox-data/chat-a"
    conflict.mkdir(parents=True)
    (conflict / "keep.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(RuntimeError, match="both"):
        migrate_user_data(tmp_path)
    assert (conflict / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert not (tmp_path / ".user-sandbox-data-v1").exists()
