"""Real checkpoint/route integration; all databases and images are temporary."""

import io
import zipfile
from functools import partial

from fastapi.testclient import TestClient

from trajectory_plugin_gateway import (
    IMAGE_PATH,
    LONG_RESULT,
    OTHER_THREAD,
    PNG,
    THREAD,
    TIMING_THREAD,
    create_app,
    state_accessor,
)

BASE = f"/api/ext-trajectory/threads/{THREAD}"
ALICE = {"x-test-user": "alice"}
BOB = {"x-test-user": "bob"}
ARTIFACT = f"/api/threads/{THREAD}/artifacts{IMAGE_PATH}"


def read_all(client):
    batches, cursor, seen = [], None, set()
    while True:
        response = client.get(
            BASE + "/checkpoints",
            headers=ALICE,
            params={"cursor": cursor} if cursor else {},
        )
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        page = response.json()
        assert not page["warnings"]
        batches.append(page["rows"])
        cursor = page["next_cursor"]
        if not cursor:
            break
        assert cursor not in seen
        seen.add(cursor)
    assert len(batches) > 1
    return [row for batch in reversed(batches) for row in batch]


def test_sqlite_reopen_restores_pre_compaction_history_and_export(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        before = read_all(client)
        response = client.get(BASE + "/export", headers=ALICE)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["content-disposition"].startswith("attachment;")
        export = response.json()
        assert export["history_complete"]
        assert export["scanned"] > 24
        assert [row["kind"] for row in export["rows"]] == [
            "user",
            "assistant",
            "tool",
            "assistant",
            "compaction",
            "user",
            "assistant",
        ]
        assert export["rows"][2]["text"] == LONG_RESULT
        comparison = export["rows"][4]["comparison"]
        assert comparison["removed_messages"][2]["text"] == LONG_RESULT
        assert comparison["after_summary"] == "COMPACTED: first turn researched"
        assert before[2]["truncated"]
        assert export["rows"][1]["tool_calls"][0]["name"] == "read_file"
    # New app, saver and connection. No writes/seeding on reopen, so this must
    # come from persisted SQLite, including messages absent from latest state.
    with TestClient(create_app(tmp_path, seed=False)) as client:
        assert read_all(client) == before
        reopened = client.get(BASE + "/export", headers=ALICE).json()
        assert reopened["rows"] == export["rows"]
        assert reopened["head_checkpoint_id"] == export["head_checkpoint_id"]
        accessor, config = state_accessor(client.app)
        current = client.portal.call(accessor.aget, config)
        assert "u1" not in [message.id for message in current.values["messages"]]
        assert client.get(ARTIFACT, headers=ALICE).content == PNG
        archive = client.get(BASE + "/export?format=markdown", headers=ALICE)
        assert archive.status_code == 200, archive.text
        with zipfile.ZipFile(io.BytesIO(archive.content)) as bundle:
            markdown = bundle.read("trajectory.md").decode()
            assert "FIRST-TURN" in markdown and "LATEST-TURN" in markdown
            assert LONG_RESULT in markdown
            assert "#### 压缩前" in markdown and "#### 压缩后" in markdown
            images = [name for name in bundle.namelist() if name.startswith("images/")]
            assert len(images) == 1
            assert images[0] in markdown
            assert bundle.read(images[0]) == PNG


def test_compaction_comparison_is_full_lazy_owner_scoped_and_survives_reopen(
    tmp_path, monkeypatch
):
    from deerflow_extension_trajectory import gateway

    with TestClient(create_app(tmp_path)) as client:
        rows = read_all(client)
        compact = next(row for row in rows if row["kind"] == "compaction")
        assert "comparison" not in compact  # Large content is read only on expansion.
        cursor = compact["comparison_cursor"]
        url = BASE + "/compaction"
        assert (
            client.get(
                f"/api/ext-trajectory/threads/{OTHER_THREAD}/compaction",
                headers=BOB,
                params={"cursor": cursor},
            ).status_code
            == 409
        )
        assert client.get(url, params={"cursor": cursor}).status_code == 401
        assert (
            client.get(url, headers=BOB, params={"cursor": cursor}).status_code == 404
        )
        assert (
            client.get(url, headers=ALICE, params={"cursor": cursor + "x"}).status_code
            == 409
        )
        response = client.get(url, headers=ALICE, params={"cursor": cursor})
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        comparison = response.json()
        assert comparison["source"] == "checkpoint_diff"
        assert [m["id"] for m in comparison["removed_messages"]] == ["u1", "a1", "t1"]
        assert comparison["removed_messages"][1]["tool_calls"][0]["name"] == "read_file"
        assert comparison["removed_messages"][2]["text"] == LONG_RESULT
        assert comparison["after_summary"] == "COMPACTED: first turn researched"
        assert comparison["before_summary"] == ""
        assert [m["id"] for m in comparison["retained_messages"]] == ["a2"]
        monkeypatch.setattr(gateway, "MAX_COMPARISON_BYTES", 10)
        assert (
            client.get(url, headers=ALICE, params={"cursor": cursor}).status_code == 413
        )

    monkeypatch.undo()
    with TestClient(create_app(tmp_path, seed=False)) as client:
        compact = next(row for row in read_all(client) if row["kind"] == "compaction")
        response = client.get(
            BASE + "/compaction",
            headers=ALICE,
            params={"cursor": compact["comparison_cursor"]},
        )
        assert response.json() == comparison
        client.portal.call(
            partial(client.app.state.thread_store.delete, THREAD, user_id="alice")
        )
        assert (
            client.get(
                BASE + "/compaction",
                headers=ALICE,
                params={"cursor": compact["comparison_cursor"]},
            ).status_code
            == 404
        )


def test_comparison_rejects_missing_history_and_non_compaction_checkpoint(tmp_path):
    from deerflow_extension_trajectory.gateway import encode_cursor

    with TestClient(create_app(tmp_path)) as client:
        first = client.app.state.first_checkpoint["configurable"]["checkpoint_id"]
        cursor = encode_cursor("alice", THREAD, first)
        assert (
            client.get(
                BASE + "/compaction", headers=ALICE, params={"cursor": cursor}
            ).status_code
            == 409
        )
        compact = next(row for row in read_all(client) if row["kind"] == "compaction")
        client.portal.call(client.app.state.checkpointer.adelete_thread, THREAD)
        response = client.get(
            BASE + "/compaction",
            headers=ALICE,
            params={"cursor": compact["comparison_cursor"]},
        )
        assert response.status_code == 409
        assert "快照" in response.json()["detail"]


def test_real_owner_acl_cursor_scope_account_switch_and_deleted_thread(
    tmp_path, monkeypatch
):
    from deerflow_extension_trajectory import gateway

    with TestClient(create_app(tmp_path)) as client:
        routes = [
            BASE + "/checkpoints",
            BASE + "/export",
            BASE + "/export?format=markdown",
            ARTIFACT,
        ]
        for url in routes:
            assert client.get(url).status_code == 401
            assert client.get(url, headers=BOB).status_code == 404
        assert not client.app.state.reads
        page = client.get(routes[0], headers=ALICE).json()
        cursor = page["next_cursor"]
        assert cursor
        # Same browser/client, different user. Ownership wins even with a
        # previously issued signed cursor and cached image URL.
        assert (
            client.get(routes[0], headers=BOB, params={"cursor": cursor}).status_code
            == 404
        )
        assert client.get(ARTIFACT, headers=BOB).status_code == 404
        other_url = f"/api/ext-trajectory/threads/{OTHER_THREAD}/checkpoints"
        assert (
            client.get(other_url, headers=BOB, params={"cursor": cursor}).status_code
            == 409
        )
        assert client.get(other_url, headers=BOB).status_code == 200
        empty_export = f"/api/ext-trajectory/threads/{TIMING_THREAD}/export"
        assert client.get(empty_export, headers=ALICE).status_code == 404
        assert (
            client.get(
                routes[0], headers=ALICE, params={"cursor": cursor + "x"}
            ).status_code
            == 409
        )
        # A new Gateway process uses a new signing key: old cursors fail closed.
        monkeypatch.setattr(gateway, "_KEY", b"new-gateway-process-key")
        assert (
            client.get(routes[0], headers=ALICE, params={"cursor": cursor}).status_code
            == 409
        )
        assert client.get(routes[0], headers=ALICE).status_code == 200
        client.portal.call(
            partial(client.app.state.thread_store.delete, THREAD, user_id="alice")
        )
        read_count = len(client.app.state.reads)
        for url in routes[:3]:
            assert client.get(url, headers=ALICE).status_code == 404
        # Host artifact reads allow absent metadata; real thread deletion also
        # removes files. Check the missing-file case separately, without
        # pretending the plugin owns the host artifact authorization policy.
        from deerflow.config.paths import get_paths

        get_paths().sandbox_uploads_dir(THREAD, user_id="alice").joinpath(
            "image_1.png"
        ).unlink()
        assert client.get(ARTIFACT, headers=ALICE).status_code == 404
        assert len(client.app.state.reads) == read_count
