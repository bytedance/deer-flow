from __future__ import annotations

from pathlib import Path

import pytest

from deerflow.config.paths import Paths
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.runs.manager import RunManager
from deerflow.runtime.runs.worker import RunContext, run_agent
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.workspace_changes import (
    WorkspaceChangeLimits,
    WorkspaceRoot,
    capture_workspace_snapshot,
    compare_snapshots,
    record_workspace_changes,
    scan_workspace_roots,
)
from deerflow.workspace_changes.api import get_workspace_changes_response
from deerflow.workspace_changes.scanner import SAMPLE_BYTES, is_sensitive_workspace_path


def _roots(tmp_path):
    workspace = tmp_path / "workspace"
    outputs = tmp_path / "outputs"
    workspace.mkdir()
    outputs.mkdir()
    return [
        WorkspaceRoot(
            name="workspace",
            host_path=workspace,
            virtual_prefix="/mnt/user-data/workspace",
        ),
        WorkspaceRoot(
            name="outputs",
            host_path=outputs,
            virtual_prefix="/mnt/user-data/outputs",
        ),
    ]


def test_compare_snapshots_reports_text_file_changes(tmp_path):
    roots = _roots(tmp_path)
    workspace = roots[0].host_path
    outputs = roots[1].host_path

    (workspace / "draft.md").write_text("alpha\nbeta\n", encoding="utf-8")
    (workspace / "old.txt").write_text("remove me\n", encoding="utf-8")
    before = scan_workspace_roots(roots)

    (workspace / "draft.md").write_text("alpha\ngamma\n", encoding="utf-8")
    (workspace / "old.txt").unlink()
    (outputs / "report.md").write_text("# Report\n\nReady\n", encoding="utf-8")
    after = scan_workspace_roots(roots)

    result = compare_snapshots(before, after)

    assert result.summary.created == 1
    assert result.summary.modified == 1
    assert result.summary.deleted == 1
    assert result.summary.additions >= 3
    assert result.summary.deletions >= 2

    changes = {change.path: change for change in result.files}
    assert changes["/mnt/user-data/workspace/draft.md"].status == "modified"
    assert "-beta" in changes["/mnt/user-data/workspace/draft.md"].diff
    assert "+gamma" in changes["/mnt/user-data/workspace/draft.md"].diff
    assert changes["/mnt/user-data/outputs/report.md"].status == "created"
    assert changes["/mnt/user-data/workspace/old.txt"].status == "deleted"


def test_compare_snapshots_treats_utf16_markdown_as_text(tmp_path):
    roots = _roots(tmp_path)
    workspace = roots[0].host_path

    before = scan_workspace_roots(roots)
    (workspace / "guide.md").write_bytes("# 标题\n\nhello\n".encode("utf-16"))
    after = scan_workspace_roots(roots)

    result = compare_snapshots(before, after)

    change = result.files[0]
    assert change.path == "/mnt/user-data/workspace/guide.md"
    assert change.binary is False
    assert change.diff_unavailable_reason is None
    assert "+# 标题" in change.diff


def test_compare_snapshots_reads_cached_utf16_markdown_baseline(tmp_path):
    roots = _roots(tmp_path)
    workspace = roots[0].host_path
    cache_dir = tmp_path / "cache"

    (workspace / "guide.md").write_bytes("# 标题\n\nhello\n".encode("utf-16"))
    before = scan_workspace_roots(roots, text_cache_dir=cache_dir)
    (workspace / "guide.md").write_bytes("# 标题\n\nupdated\n".encode("utf-16"))
    after = scan_workspace_roots(roots)

    result = compare_snapshots(before, after)

    change = result.files[0]
    assert change.binary is False
    assert change.diff_unavailable_reason is None
    assert "-hello" in change.diff
    assert "+updated" in change.diff


def test_compare_snapshots_treats_utf8_markdown_crossing_sample_boundary_as_text(
    tmp_path,
):
    roots = _roots(tmp_path)
    workspace = roots[0].host_path

    before = scan_workspace_roots(roots)
    content = ("a" * (SAMPLE_BYTES - 1)) + "你" + "\nrest\n"
    (workspace / "guide.md").write_text(content, encoding="utf-8")
    after = scan_workspace_roots(roots)

    result = compare_snapshots(before, after)

    change = result.files[0]
    assert change.path == "/mnt/user-data/workspace/guide.md"
    assert change.binary is False
    assert "你" in change.diff
    assert "+rest" in change.diff


def test_compare_snapshots_strips_utf8_bom(tmp_path):
    roots = _roots(tmp_path)
    workspace = roots[0].host_path

    before = scan_workspace_roots(roots)
    content = "# 标题\n\nhello\n".encode()
    (workspace / "guide.md").write_bytes(b"\xef\xbb\xbf" + content)
    after = scan_workspace_roots(roots)

    result = compare_snapshots(before, after)

    change = result.files[0]
    assert change.path == "/mnt/user-data/workspace/guide.md"
    assert change.binary is False
    assert change.diff_unavailable_reason is None
    assert "\ufeff" not in change.diff
    assert "+# 标题" in change.diff


def test_compare_snapshots_keeps_nul_bytes_classified_as_binary(tmp_path):
    roots = _roots(tmp_path)
    workspace = roots[0].host_path

    before = scan_workspace_roots(roots)
    (workspace / "guide.md").write_bytes(b"\x00\x01\x02binary\n")
    after = scan_workspace_roots(roots)

    result = compare_snapshots(before, after)

    change = result.files[0]
    assert change.path == "/mnt/user-data/workspace/guide.md"
    assert change.binary is True
    assert change.diff == ""
    assert change.diff_unavailable_reason == "binary"


def test_count_diff_lines_ignores_only_real_headers():
    from deerflow.workspace_changes.diff import _count_diff_lines

    lines = [
        "--- a/mnt/user-data/workspace/file.txt",
        "+++ b/mnt/user-data/workspace/file.txt",
        "@@ -1,2 +1,2 @@",
        "-old",
        "+new",
        # Content lines that happen to start with +++/--- must still count.
        "+++added",
        "---removed",
    ]

    additions, deletions = _count_diff_lines(lines)

    assert additions == 2
    assert deletions == 2


def test_scan_workspace_roots_skips_excluded_directories(tmp_path):
    roots = _roots(tmp_path)
    workspace = roots[0].host_path
    (workspace / "visible.txt").write_text("visible", encoding="utf-8")
    (workspace / "node_modules").mkdir()
    (workspace / "node_modules" / "ignored.js").write_text(
        "ignored",
        encoding="utf-8",
    )

    snapshot = scan_workspace_roots(roots)

    assert "/mnt/user-data/workspace/visible.txt" in snapshot.files
    assert "/mnt/user-data/workspace/node_modules/ignored.js" not in snapshot.files


def test_scan_workspace_roots_can_skip_text_loading(tmp_path):
    roots = _roots(tmp_path)
    workspace = roots[0].host_path
    (workspace / "visible.txt").write_text("visible", encoding="utf-8")

    snapshot = scan_workspace_roots(roots, include_text=False)
    file = snapshot.files["/mnt/user-data/workspace/visible.txt"]

    assert file.sha256 is not None
    assert file.text is None
    assert file.content_unavailable_reason is None


def test_sensitive_workspace_path_covers_common_secret_names():
    for filename in (
        "password.txt",
        "api_key.txt",
        "apikey",
        "private_key.json",
    ):
        assert is_sensitive_workspace_path(f"/mnt/user-data/workspace/{filename}")


def test_compare_snapshots_hides_sensitive_and_binary_file_content(tmp_path):
    roots = _roots(tmp_path)
    workspace = roots[0].host_path

    before = scan_workspace_roots(roots)
    (workspace / ".env").write_text("SECRET_TOKEN=abc\n", encoding="utf-8")
    (workspace / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00binary")
    after = scan_workspace_roots(roots)

    result = compare_snapshots(before, after)
    changes = {change.path: change for change in result.files}

    env_change = changes["/mnt/user-data/workspace/.env"]
    assert env_change.sensitive is True
    assert env_change.sha256_before is None
    assert env_change.sha256_after is None
    assert env_change.diff == ""
    assert env_change.diff_unavailable_reason == "sensitive"

    binary_change = changes["/mnt/user-data/workspace/image.png"]
    assert binary_change.binary is True
    assert binary_change.diff == ""
    assert binary_change.diff_unavailable_reason == "binary"


@pytest.fixture
def symlink_support(tmp_path):
    # Real symlink creation needs elevated privilege on stock Windows (no Developer
    # Mode / admin); skip gracefully there instead of failing the whole run. Linux/CI
    # and WSL create symlinks natively, so this exercises the real behavior there.
    probe_link = tmp_path / "_symlink_probe"
    try:
        probe_link.symlink_to(tmp_path)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is not permitted on this platform/user")
    probe_link.unlink()


def test_compare_snapshots_classifies_symlink_replacing_file_as_symlink_created(tmp_path, symlink_support):
    roots = _roots(tmp_path)
    workspace = roots[0].host_path
    outside_target = tmp_path / "outside-secret.txt"
    outside_target.write_text("host-side content outside the workspace root\n", encoding="utf-8")

    (workspace / "config.txt").write_text("original tracked content\n", encoding="utf-8")
    before = scan_workspace_roots(roots)
    assert before.files["/mnt/user-data/workspace/config.txt"].symlink is False

    # Simulate an agent run doing: rm config.txt && ln -s <outside path> config.txt
    (workspace / "config.txt").unlink()
    (workspace / "config.txt").symlink_to(outside_target)
    after = scan_workspace_roots(roots)

    result = compare_snapshots(before, after)
    changes = {change.path: change for change in result.files}
    change = changes["/mnt/user-data/workspace/config.txt"]

    assert change.status == "symlink_created"
    assert change.status != "deleted"
    assert change.symlink is True
    assert change.symlink_target_after == str(outside_target)
    assert change.diff_unavailable_reason == "symlink"
    assert change.diff == ""
    assert result.summary.symlink_created == 1
    assert result.summary.deleted == 0
    assert result.has_changes() is True


def test_scan_workspace_roots_captures_symlinks_as_metadata_only_stubs(tmp_path, symlink_support):
    roots = _roots(tmp_path)
    workspace = roots[0].host_path
    outside_target = tmp_path / "outside-target.txt"
    outside_target.write_text("outside content\n", encoding="utf-8")
    (workspace / "link.txt").symlink_to(outside_target)

    snapshot = scan_workspace_roots(roots)
    file = snapshot.files["/mnt/user-data/workspace/link.txt"]

    assert file.symlink is True
    assert file.symlink_target == str(outside_target)
    assert file.text is None
    assert file.sha256 is None
    assert file.content_unavailable_reason == "symlink"


def test_compare_snapshots_reports_removed_symlink_without_replacement_as_deleted(tmp_path, symlink_support):
    # Scope boundary: a symlink that is genuinely removed with nothing taking its
    # place is still "deleted" - only a symlink *newly occupying* a path (created or
    # replacing a prior non-symlink) gets the distinct "symlink_created" status.
    roots = _roots(tmp_path)
    workspace = roots[0].host_path
    outside_target = tmp_path / "outside-target.txt"
    outside_target.write_text("outside content\n", encoding="utf-8")
    (workspace / "link.txt").symlink_to(outside_target)
    before = scan_workspace_roots(roots)

    (workspace / "link.txt").unlink()
    after = scan_workspace_roots(roots)

    result = compare_snapshots(before, after)
    changes = {change.path: change for change in result.files}
    assert changes["/mnt/user-data/workspace/link.txt"].status == "deleted"


def test_compare_snapshots_truncates_large_text_diffs(tmp_path):
    roots = _roots(tmp_path)
    workspace = roots[0].host_path
    before = scan_workspace_roots(roots)
    (workspace / "large.txt").write_text("0123456789\n" * 20, encoding="utf-8")
    after = scan_workspace_roots(
        roots,
        limits=WorkspaceChangeLimits(max_file_bytes_for_diff=32),
    )

    result = compare_snapshots(before, after)

    change = result.files[0]
    assert change.path == "/mnt/user-data/workspace/large.txt"
    assert change.sha256_before is None
    assert change.sha256_after is None
    assert change.diff == ""
    assert change.diff_unavailable_reason == "large"
    assert result.summary.truncated is True


@pytest.mark.asyncio
async def test_workspace_changes_response_returns_summary_only_and_full_payload():
    store = MemoryRunEventStore()
    payload = {
        "version": 1,
        "summary": {
            "created": 1,
            "modified": 0,
            "deleted": 0,
            "additions": 2,
            "deletions": 0,
            "truncated": False,
        },
        "files": [
            {
                "path": "/mnt/user-data/outputs/report.md",
                "root": "outputs",
                "status": "created",
                "binary": False,
                "sensitive": False,
                "size_before": None,
                "size_after": 12,
                "sha256_before": None,
                "sha256_after": "abc",
                "diff": "+hello",
                "diff_truncated": False,
                "diff_unavailable_reason": None,
                "additions": 1,
                "deletions": 0,
            }
        ],
        "limits": {
            "max_files": 200,
            "max_file_bytes_for_diff": 262144,
            "max_total_diff_bytes": 1048576,
        },
    }
    await store.put(
        thread_id="thread-1",
        run_id="run-1",
        event_type="workspace_changes",
        category="workspace",
        content="1 file changed +2 -0",
        metadata={"workspace_changes": payload},
    )

    summary = await get_workspace_changes_response(
        store,
        "thread-1",
        "run-1",
        include_files=False,
    )
    metadata_only = await get_workspace_changes_response(
        store,
        "thread-1",
        "run-1",
        include_files=True,
        include_diff=False,
    )
    full = await get_workspace_changes_response(
        store,
        "thread-1",
        "run-1",
        include_files=True,
    )

    assert summary["available"] is True
    assert summary["summary"]["created"] == 1
    assert summary["files"] == []
    assert metadata_only["files"][0]["path"] == "/mnt/user-data/outputs/report.md"
    assert metadata_only["files"][0]["diff"] == ""
    assert full["files"][0]["diff"] == "+hello"


@pytest.mark.asyncio
async def test_workspace_changes_response_is_empty_when_no_event_exists():
    response = await get_workspace_changes_response(
        MemoryRunEventStore(),
        "thread-1",
        "run-1",
    )

    assert response["available"] is False
    assert response["summary"] == {
        "created": 0,
        "modified": 0,
        "deleted": 0,
        "symlink_created": 0,
        "additions": 0,
        "deletions": 0,
        "truncated": False,
    }
    assert response["files"] == []


@pytest.mark.anyio
async def test_run_agent_records_workspace_changes_event(tmp_path, monkeypatch):
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "_paths", Paths(tmp_path))

    event_store = MemoryRunEventStore()
    run_manager = RunManager()
    record = await run_manager.create("thread-1")
    user_id = get_effective_user_id()
    paths_module.get_paths().ensure_thread_dirs("thread-1", user_id=user_id)

    class DummyBridge:
        async def publish(self, run_id, event, data):
            return None

        async def publish_end(self, run_id):
            return None

        async def cleanup(self, run_id, delay):
            return None

    class DummyAgent:
        async def astream(self, graph_input, config=None, stream_mode=None, subgraphs=False):
            workspace = paths_module.get_paths().sandbox_work_dir("thread-1", user_id=user_id)
            (workspace / "report.md").write_text("# Report\n\nReady\n", encoding="utf-8")
            yield {"messages": []}

    def factory(*, config):
        return DummyAgent()

    await run_agent(
        DummyBridge(),
        run_manager,
        record,
        ctx=RunContext(checkpointer=None, event_store=event_store),
        agent_factory=factory,
        graph_input={},
        config={},
    )

    events = await event_store.list_events(
        "thread-1",
        record.run_id,
        event_types=["workspace_changes"],
    )
    assert len(events) == 1
    payload = events[0]["metadata"]["workspace_changes"]
    assert payload["summary"]["created"] == 1
    assert payload["files"][0]["path"] == "/mnt/user-data/workspace/report.md"
    assert "+# Report" in payload["files"][0]["diff"]


@pytest.mark.anyio
async def test_record_workspace_changes_content_uses_total_changed_count(tmp_path, monkeypatch):
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "_paths", Paths(tmp_path))
    user_id = get_effective_user_id()
    paths_module.get_paths().ensure_thread_dirs("thread-1", user_id=user_id)
    workspace = paths_module.get_paths().sandbox_work_dir("thread-1", user_id=user_id)
    (workspace / "unchanged.txt").write_text("keep me\n", encoding="utf-8")

    before = await capture_workspace_snapshot(
        "thread-1",
        user_id=user_id,
        limits=WorkspaceChangeLimits(max_files=1),
    )
    (workspace / "a.txt").write_text("a\n", encoding="utf-8")
    (workspace / "b.txt").write_text("b\n", encoding="utf-8")

    assert before.files["/mnt/user-data/workspace/unchanged.txt"].text is None

    store = MemoryRunEventStore()
    await record_workspace_changes(
        store,
        "thread-1",
        "run-1",
        before,
        user_id=user_id,
        limits=WorkspaceChangeLimits(max_files=1),
    )

    events = await store.list_events("thread-1", "run-1", event_types=["workspace_changes"])
    assert events[0]["content"] == "2 files changed +2 -0"
    payload = events[0]["metadata"]["workspace_changes"]
    assert payload["summary"]["created"] == 2
    assert len(payload["files"]) == 1


@pytest.mark.anyio
async def test_record_workspace_changes_uses_cached_baseline_for_modified_diff(tmp_path, monkeypatch):
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "_paths", Paths(tmp_path))
    user_id = get_effective_user_id()
    paths_module.get_paths().ensure_thread_dirs("thread-1", user_id=user_id)
    workspace = paths_module.get_paths().sandbox_work_dir("thread-1", user_id=user_id)
    (workspace / "edit.txt").write_text("old\n", encoding="utf-8")

    before = await capture_workspace_snapshot("thread-1", user_id=user_id)
    assert before.files["/mnt/user-data/workspace/edit.txt"].text is None
    assert before.text_cache_dir is not None
    text_cache_dir = Path(before.text_cache_dir)
    assert text_cache_dir.exists()

    (workspace / "edit.txt").write_text("new\n", encoding="utf-8")

    store = MemoryRunEventStore()
    await record_workspace_changes(
        store,
        "thread-1",
        "run-1",
        before,
        user_id=user_id,
    )

    events = await store.list_events("thread-1", "run-1", event_types=["workspace_changes"])
    diff = events[0]["metadata"]["workspace_changes"]["files"][0]["diff"]
    assert "-old" in diff
    assert "+new" in diff
    assert not text_cache_dir.exists()


@pytest.mark.anyio
async def test_workspace_changes_route_forwards_include_files_flag():
    from app.gateway.routers.thread_runs import get_run_workspace_changes

    calls: dict = {}

    class FakeStore:
        async def list_events(self, thread_id, run_id, *, event_types=None, task_id=None, limit=500, after_seq=None):
            calls.update(thread_id=thread_id, run_id=run_id, event_types=event_types)
            return [
                {
                    "metadata": {
                        "workspace_changes": {
                            "version": 1,
                            "summary": {
                                "created": 1,
                                "modified": 0,
                                "deleted": 0,
                                "additions": 1,
                                "deletions": 0,
                                "truncated": False,
                            },
                            "files": [{"path": "/mnt/user-data/workspace/report.md", "diff": "+hello"}],
                            "limits": {},
                        }
                    }
                }
            ]

    class FakeState:
        run_event_store = FakeStore()

    class FakeApp:
        state = FakeState()

    class FakeRequest:
        app = FakeApp()
        _deerflow_test_bypass_auth = True

    response = await get_run_workspace_changes(
        thread_id="thread-1",
        run_id="run-1",
        request=FakeRequest(),
        include_files=False,
        include_diff=False,
    )

    assert response["available"] is True
    assert response["files"] == []
    assert calls["event_types"] == ["workspace_changes"]
