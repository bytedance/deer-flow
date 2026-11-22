from __future__ import annotations

import hashlib
import os
import threading
from types import SimpleNamespace

import pytest
from langchain_core.messages import ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from support.symlinks import symlink_or_skip

from deerflow.config.paths import Paths

pytestmark = pytest.mark.skipif(os.name != "posix", reason="descriptor-confined artifact snapshots require POSIX")


def _runtime(paths: Paths, thread_id: str, user_id: str):
    return SimpleNamespace(
        state={"thread_data": {"outputs_path": str(paths.sandbox_outputs_dir(thread_id, user_id=user_id))}},
        context={"thread_id": thread_id, "user_id": user_id},
        config={},
    )


def _source(paths: Paths, thread_id: str, user_id: str, content: bytes) -> str:
    directory = paths.sandbox_outputs_dir(thread_id, user_id=user_id)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "alpha.json").write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def _invoke(runtime, origin: str, digest: str, path: str = "/mnt/user-data/outputs/alpha.json"):
    from deerflow.tools.artifact_handoff import present_shared_artifact

    return present_shared_artifact.func(runtime=runtime, origin_thread_id=origin, path=path, sha256=digest, tool_call_id="test-call")


def test_source_bound_artifact_is_published_without_overwriting_source(tmp_path, monkeypatch):
    paths = Paths(tmp_path)
    monkeypatch.setattr("deerflow.tools.artifact_handoff.get_paths", lambda: paths)
    content = b'{"revenue":450,"profit":210,"teams":3}'
    digest = _source(paths, "worker", "user", content)
    destination = paths.sandbox_outputs_dir("main", user_id="user")
    destination.mkdir(parents=True)

    result = _invoke(_runtime(paths, "main", "user"), "worker", digest)

    assert result.update["artifacts"] == ["/mnt/user-data/outputs/alpha.json"]
    assert (destination / "alpha.json").read_bytes() == content
    assert (paths.sandbox_outputs_dir("worker", user_id="user") / "alpha.json").read_bytes() == content
    message = result.update["messages"][0]
    assert isinstance(message, ToolMessage)
    assert message.content == f"Successfully presented shared artifact; origin_thread_id=worker; sha256={digest}"


def test_wrong_hash_preserves_existing_destination(tmp_path, monkeypatch):
    paths = Paths(tmp_path)
    monkeypatch.setattr("deerflow.tools.artifact_handoff.get_paths", lambda: paths)
    _source(paths, "worker", "user", b"new revision")
    destination = paths.sandbox_outputs_dir("main", user_id="user")
    destination.mkdir(parents=True)
    (destination / "alpha.json").write_bytes(b"existing revision")

    result = _invoke(_runtime(paths, "main", "user"), "worker", "0" * 64)

    assert "Error:" in result.update["messages"][0].content
    assert "artifacts" not in result.update
    assert (destination / "alpha.json").read_bytes() == b"existing revision"


def test_changed_source_revision_is_not_accepted(tmp_path, monkeypatch):
    paths = Paths(tmp_path)
    monkeypatch.setattr("deerflow.tools.artifact_handoff.get_paths", lambda: paths)
    _source(paths, "worker", "user", b"new revision")

    result = _invoke(_runtime(paths, "main", "user"), "worker", "0" * 64)

    assert "Error:" in result.update["messages"][0].content
    assert "artifacts" not in result.update


def test_source_path_cannot_escape_outputs(tmp_path, monkeypatch):
    paths = Paths(tmp_path)
    monkeypatch.setattr("deerflow.tools.artifact_handoff.get_paths", lambda: paths)
    destination = paths.sandbox_outputs_dir("main", user_id="user")
    destination.mkdir(parents=True)

    result = _invoke(_runtime(paths, "main", "user"), "worker", "0" * 64, "/mnt/user-data/outputs/../uploads/alpha.json")

    assert "Error:" in result.update["messages"][0].content
    assert "artifacts" not in result.update
    assert not (destination / "alpha.json").exists()


def test_symlinked_source_is_rejected(tmp_path, monkeypatch):
    if not hasattr(os, "O_NOFOLLOW"):
        pytest.skip("requires O_NOFOLLOW")
    paths = Paths(tmp_path)
    monkeypatch.setattr("deerflow.tools.artifact_handoff.get_paths", lambda: paths)
    _source(paths, "worker", "user", b"content")
    source = paths.sandbox_outputs_dir("worker", user_id="user") / "alpha.json"
    source.unlink()
    source.symlink_to(tmp_path / "outside.json")
    (tmp_path / "outside.json").write_bytes(b"content")

    result = _invoke(_runtime(paths, "main", "user"), "worker", "0" * 64)

    assert "Error:" in result.update["messages"][0].content
    assert "artifacts" not in result.update


def test_symlinked_source_outputs_root_cannot_read_another_user(tmp_path, monkeypatch):
    paths = Paths(tmp_path)
    monkeypatch.setattr("deerflow.tools.artifact_handoff.get_paths", lambda: paths)
    content = b"other user's private bytes"
    digest = _source(paths, "worker", "other", content)
    source_root = paths.sandbox_outputs_dir("worker", user_id="user")
    source_root.parent.mkdir(parents=True)
    symlink_or_skip(source_root, paths.sandbox_outputs_dir("worker", user_id="other"), target_is_directory=True)
    destination = paths.sandbox_outputs_dir("main", user_id="user")
    destination.mkdir(parents=True)

    result = _invoke(_runtime(paths, "main", "user"), "worker", digest)

    assert "Error:" in result.update["messages"][0].content
    assert "artifacts" not in result.update
    assert not (destination / "alpha.json").exists()


def test_symlinked_destination_outputs_root_cannot_write_another_user(tmp_path, monkeypatch):
    paths = Paths(tmp_path)
    monkeypatch.setattr("deerflow.tools.artifact_handoff.get_paths", lambda: paths)
    digest = _source(paths, "worker", "user", b"source bytes")
    other_destination = paths.sandbox_outputs_dir("main", user_id="other")
    other_destination.mkdir(parents=True)
    destination = paths.sandbox_outputs_dir("main", user_id="user")
    destination.parent.mkdir(parents=True)
    symlink_or_skip(destination, other_destination, target_is_directory=True)

    result = _invoke(_runtime(paths, "main", "user"), "worker", digest)

    assert "Error:" in result.update["messages"][0].content
    assert "artifacts" not in result.update
    assert not (other_destination / "alpha.json").exists()


def test_invalid_thread_and_hash_are_rejected(tmp_path, monkeypatch):
    paths = Paths(tmp_path)
    monkeypatch.setattr("deerflow.tools.artifact_handoff.get_paths", lambda: paths)

    for origin, digest in [("../worker", "0" * 64), ("worker", "not-a-hash")]:
        result = _invoke(_runtime(paths, "main", "user"), origin, digest)
        assert "Error:" in result.update["messages"][0].content
        assert "artifacts" not in result.update


def test_concurrent_handoffs_of_identical_bytes_both_succeed(tmp_path, monkeypatch):
    paths = Paths(tmp_path)
    monkeypatch.setattr("deerflow.tools.artifact_handoff.get_paths", lambda: paths)
    digest = _source(paths, "worker", "user", b"identical bytes")
    runtime = _runtime(paths, "main", "user")
    first_linked = threading.Event()
    release_first = threading.Event()
    second_link_attempted = threading.Event()
    second_checked = threading.Event()
    real_link = os.link
    real_fstat = os.fstat
    import fcntl

    real_flock = fcntl.flock

    def gated_flock(descriptor, operation):
        if threading.current_thread().name == "second-handoff" and operation == fcntl.LOCK_EX:
            second_checked.set()
        return real_flock(descriptor, operation)

    def gated_link(source, destination, **kwargs):
        if threading.current_thread().name == "first-handoff":
            result = real_link(source, destination, **kwargs)
            first_linked.set()
            assert release_first.wait(5)
            return result
        try:
            return real_link(source, destination, **kwargs)
        finally:
            second_link_attempted.set()

    def gated_fstat(descriptor):
        result = real_fstat(descriptor)
        if threading.current_thread().name == "second-handoff" and second_link_attempted.is_set():
            second_checked.set()
        return result

    monkeypatch.setattr(fcntl, "flock", gated_flock)
    monkeypatch.setattr(os, "link", gated_link)
    monkeypatch.setattr(os, "fstat", gated_fstat)
    results = {}

    def invoke(name):
        results[name] = _invoke(runtime, "worker", digest)

    first = threading.Thread(target=invoke, args=("first",), name="first-handoff")
    second = threading.Thread(target=invoke, args=("second",), name="second-handoff")
    threads = []
    try:
        first.start()
        threads.append(first)
        assert first_linked.wait(5)
        second.start()
        threads.append(second)
        assert second_checked.wait(5)
    finally:
        release_first.set()
        for thread in threads:
            thread.join(timeout=5)

    assert all(not thread.is_alive() for thread in threads)
    assert set(results) == {"first", "second"}
    for result in results.values():
        assert result.update.get("artifacts") == ["/mnt/user-data/outputs/alpha.json"], result.update["messages"][0].content
    assert (paths.sandbox_outputs_dir("main", user_id="user") / "alpha.json").read_bytes() == b"identical bytes"


def test_shared_artifact_schema_exposes_source_contract():
    from deerflow.tools.artifact_handoff import present_shared_artifact

    parameters = convert_to_openai_tool(present_shared_artifact)["function"]["parameters"]
    assert set(parameters["properties"]) == {"origin_thread_id", "path", "sha256"}
    assert set(parameters["required"]) == {"origin_thread_id", "path", "sha256"}


def test_shared_artifact_is_registered_as_a_builtin_tool():
    from deerflow.tools.artifact_handoff import present_shared_artifact
    from deerflow.tools.tools import BUILTIN_TOOLS

    assert present_shared_artifact in BUILTIN_TOOLS


@pytest.mark.no_auto_user
def test_shared_artifact_runs_through_real_agent_graph(tmp_path, monkeypatch):
    from _agent_e2e_helpers import FakeToolCallingModel
    from langchain_core.messages import AIMessage, HumanMessage
    from langgraph.runtime import Runtime

    from deerflow.agents.factory import create_deerflow_agent
    from deerflow.agents.middlewares.thread_data_middleware import ThreadDataMiddleware
    from deerflow.agents.thread_state import ThreadState
    from deerflow.tools.artifact_handoff import present_shared_artifact

    paths = Paths(tmp_path)
    monkeypatch.setattr("deerflow.tools.artifact_handoff.get_paths", lambda: paths)
    content = b'{"revenue":450}'
    digest = _source(paths, "worker", "user", content)
    model = FakeToolCallingModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[{"name": "present_shared_artifact", "args": {"origin_thread_id": "worker", "path": "/mnt/user-data/outputs/alpha.json", "sha256": digest}, "id": "call_shared", "type": "tool_call"}],
            ),
            AIMessage(content="Presented the shared file."),
        ]
    )
    graph = create_deerflow_agent(
        model,
        tools=[present_shared_artifact],
        middleware=[ThreadDataMiddleware(base_dir=str(tmp_path), lazy_init=True)],
        state_schema=ThreadState,
        system_prompt="Deliver the worker's artifact.",
    )
    runtime = Runtime(context={"thread_id": "main", "user_id": "user"}, store=None)

    result = graph.invoke(
        {"messages": [HumanMessage(content="Deliver alpha.json")]},
        config={"configurable": {"thread_id": "main", "__pregel_runtime": runtime}, "recursion_limit": 20},
    )

    assert result["artifacts"] == ["/mnt/user-data/outputs/alpha.json"]
    assert (paths.sandbox_outputs_dir("main", user_id="user") / "alpha.json").read_bytes() == content
