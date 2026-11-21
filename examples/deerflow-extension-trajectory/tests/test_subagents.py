"""Subagent discovery, scoped paging and SQLite reopen through real routes."""

import io
import json
import sqlite3
import zipfile

import pytest
from fastapi.testclient import TestClient
from trajectory_plugin_gateway import CHILD_THREAD, create_app

BASE = f"/api/ext-trajectory/threads/{CHILD_THREAD}"
OWNER = {"x-test-user": "alice"}


def parent_page(client):
    response = client.get(BASE + "/checkpoints", headers=OWNER)
    assert response.status_code == 200
    return response.json()


@pytest.mark.parametrize("mode", ["full", "delta"])
def test_children_match_the_saved_invocation_and_reopen(tmp_path, mode):
    recorded = None
    for seed in [True, False]:
        with TestClient(create_app(tmp_path, seed=seed, mode=mode)) as client:
            page = parent_page(client)
            calls = [
                call
                for row in page["rows"]
                for call in row.get("tool_calls", [])
                if call["name"] == "task"
            ]
            assert calls and all(call.get("subagent_cursor") for call in calls)
            # Same provider IDs were reused by a second parent run.
            latest = calls[-2:]
            found = []
            for call in latest:
                response = client.get(
                    BASE + "/subagents",
                    headers=OWNER,
                    params={"cursor": call["subagent_cursor"]},
                )
                assert response.status_code == 200, response.text
                children = response.json()["children"]
                assert len(children) == 1
                child = children[0]
                assert child["execution_id"].startswith(
                    "parent-two-" + call["id"] + "-"
                )
                assert child["parent_run_id"] == "parent-two"
                assert child["tool_call_id"] == call["id"]
                cursor = child["cursor"]
                batches = []
                while cursor:
                    response = client.get(
                        BASE + "/subagent-checkpoints",
                        headers=OWNER,
                        params={"cursor": cursor},
                    )
                    assert response.status_code == 200, response.text
                    data = response.json()
                    assert not data["warnings"]
                    batches.append(data["rows"])
                    cursor = data["next_cursor"]
                assert len(batches) > 1
                rows = [row for batch in reversed(batches) for row in batch]
                assert [row["kind"] for row in rows] == [
                    "user",
                    "assistant",
                    "tool",
                    "assistant",
                ]
                assert rows[2]["tool_call_id"] == "internal-call"
                assert rows[2]["truncated"]
                assert child["execution_id"] in rows[-1]["text"]
                found.append(rows)
            export = client.get(BASE + "/export", headers=OWNER)
            assert export.status_code == 200, export.text
            data = export.json()
            assert data["history_complete"]
            children = [
                child
                for row in data["rows"]
                for call in row.get("tool_calls", [])
                for child in call.get("subagents", [])
            ]
            assert len(children) == 4
            assert len({child["execution_id"] for child in children}) == 4
            assert all(
                "CHILD-TOOL-END" in child["rows"][2]["text"] for child in children
            )
            assert all(not child["rows"][2]["truncated"] for child in children)
            if seed:
                recorded = found
                archive = client.get(BASE + "/export?format=markdown", headers=OWNER)
                assert archive.status_code == 200, archive.text
                with zipfile.ZipFile(io.BytesIO(archive.content)) as bundle:
                    markdown = bundle.read("trajectory.md").decode()
                    assert "子 agent 轨迹" in markdown
                    assert "parent-one-outer-shared" in markdown
                    assert "parent-two-outer-second" in markdown
                    assert markdown.count("CHILD-TOOL-END") == 4
            else:
                assert found == recorded


@pytest.mark.parametrize(
    "mode,persist_parent_run_id", [("full", False), ("delta", False), ("full", True)]
)
def test_reused_call_ids_match_each_dispatch_message(
    tmp_path, mode, persist_parent_run_id
):
    with TestClient(
        create_app(
            tmp_path,
            mode=mode,
            persist_parent_run_id=persist_parent_run_id,
            repeat_in_run=True,
        )
    ) as client:
        with sqlite3.connect(tmp_path / "checkpoints.sqlite") as connection:
            metadata = [
                json.loads(row[0])
                for row in connection.execute(
                    "SELECT metadata FROM checkpoints WHERE thread_id=? AND checkpoint_ns=''",
                    (CHILD_THREAD,),
                )
            ]
        assert metadata
        assert all(("run_id" in entry) == persist_parent_run_id for entry in metadata)
        calls = [
            call
            for row in parent_page(client)["rows"]
            for call in row.get("tool_calls", [])
            if call["name"] == "task"
        ]
        assert len(calls) == 8
        executions = set()
        for index, call in enumerate(calls):
            response = client.get(
                BASE + "/subagents",
                headers=OWNER,
                params={"cursor": call["subagent_cursor"]},
            )
            assert response.status_code == 200, response.text
            data = response.json()
            assert not data["warnings"]
            assert len(data["children"]) == 1
            child = data["children"][0]
            assert child["parent_run_id"] == (
                "parent-one" if index < 4 else "parent-two"
            )
            assert child["tool_call_id"] == call["id"]
            assert child["execution_id"] not in executions
            executions.add(child["execution_id"])


def test_child_routes_require_owner_and_scoped_signed_cursors(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        call = next(
            call
            for row in parent_page(client)["rows"]
            for call in row.get("tool_calls", [])
            if call["name"] == "task"
        )
        token = call["subagent_cursor"]
        child = client.get(
            BASE + "/subagents", headers=OWNER, params={"cursor": token}
        ).json()["children"][0]
        for route, cursor in [
            ("subagents", token),
            ("subagent-checkpoints", child["cursor"]),
        ]:
            url = BASE + "/" + route
            assert client.get(url, params={"cursor": cursor}).status_code == 401
            assert (
                client.get(
                    url, headers={"x-test-user": "bob"}, params={"cursor": cursor}
                ).status_code
                == 404
            )
            assert (
                client.get(
                    url, headers=OWNER, params={"cursor": cursor + "tampered"}
                ).status_code
                == 409
            )
        # A discovery token cannot be used to select arbitrary child state.
        assert (
            client.get(
                BASE + "/subagent-checkpoints", headers=OWNER, params={"cursor": token}
            ).status_code
            == 409
        )
        from trajectory_plugin_gateway import THREAD

        assert (
            client.get(
                f"/api/ext-trajectory/threads/{THREAD}/subagents",
                headers=OWNER,
                params={"cursor": token},
            ).status_code
            == 409
        )


def test_child_discovery_rejects_unrelated_parent_checkpoint(tmp_path):
    from deerflow_extension_trajectory.gateway import scoped_cursor

    with TestClient(create_app(tmp_path)) as client:
        # A later parent checkpoint still contains the call, but the child's
        # recorded parent chain cannot descend from a future checkpoint.
        page = parent_page(client)
        checkpoint = page["rows"][-1]["checkpoint_id"]
        token = scoped_cursor(
            "alice",
            CHILD_THREAD,
            "invocation",
            checkpoint_id=checkpoint,
            tool_call_id="outer-shared",
        )
        response = client.get(
            BASE + "/subagents", headers=OWNER, params={"cursor": token}
        )
        assert response.status_code == 200
        assert not response.json()["children"]


def test_bounded_discovery_releases_sqlite_iterator_before_more_reads(
    tmp_path, monkeypatch
):
    from deerflow_extension_trajectory import subagents

    with TestClient(create_app(tmp_path)) as client:
        call = next(
            call
            for row in parent_page(client)["rows"]
            for call in row.get("tool_calls", [])
            if call["name"] == "task"
        )
        params = {"cursor": call["subagent_cursor"]}
        with monkeypatch.context() as limited:
            limited.setattr(subagents, "MAX_DISCOVERY_CHECKPOINTS", 1)
            response = client.get(BASE + "/subagents", headers=OWNER, params=params)
            assert response.status_code == 200
            assert response.json()["warnings"]
        # The saver remains usable after a truncated async iteration.
        response = client.get(BASE + "/subagents", headers=OWNER, params=params)
        assert response.status_code == 200
        assert not response.json()["warnings"]
        assert len(response.json()["children"]) == 1


def test_missing_child_checkpoint_reports_missing_evidence(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        call = next(
            call
            for row in parent_page(client)["rows"]
            for call in row.get("tool_calls", [])
            if call["name"] == "task"
        )
        params = {"cursor": call["subagent_cursor"]}
        child = client.get(BASE + "/subagents", headers=OWNER, params=params).json()[
            "children"
        ][0]
        with sqlite3.connect(tmp_path / "checkpoints.sqlite") as connection:
            connection.execute(
                "DELETE FROM checkpoints WHERE thread_id=? AND checkpoint_ns=?",
                (CHILD_THREAD, child["checkpoint_ns"]),
            )
        response = client.get(
            BASE + "/subagent-checkpoints",
            headers=OWNER,
            params={"cursor": child["cursor"]},
        )
        assert response.status_code == 409
        assert "缺失" in response.json()["detail"]
        response = client.get(BASE + "/subagents", headers=OWNER, params=params)
        assert response.status_code == 200
        assert not response.json()["children"]
