"""Malformed client upload metadata must not abort a valid chat turn."""

import asyncio
import logging
import os
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import Field

from app.gateway.services import _normalize_input_messages
from deerflow.agents.middlewares.input_sanitization_middleware import InputSanitizationMiddleware
from deerflow.agents.middlewares.uploads_middleware import UploadsMiddleware
from deerflow.tools.builtins.list_uploaded_files_tool import _list_uploaded_files_impl
from deerflow.utils.messages import ORIGINAL_USER_CONTENT_KEY, message_content_to_text
from deerflow.utils.upload_context import project_upload_context


@pytest.fixture
def upload_context(tmp_path):
    middleware = UploadsMiddleware(base_dir=str(tmp_path))
    context = {"thread_id": "upload-thread", "user_id": "alice"}
    directory = middleware._paths.sandbox_uploads_dir(**context)
    directory.mkdir(parents=True)
    (directory / "current.md").write_text("# Current document\n\nNew evidence", encoding="utf-8")
    (directory / "historical.md").write_text("# Historical document", encoding="utf-8")
    return middleware, directory, context


def _gateway_message(files):
    return _normalize_input_messages(
        [{"role": "user", "content": "Read the attachment", "additional_kwargs": {"files": files}}],
        location="input.messages",
    )[0]


@pytest.mark.parametrize("filename", [True, 123, 1.5, ["current.md"], {"name": "current.md"}])
def test_gateway_metadata_keeps_valid_siblings_when_a_filename_is_not_text(upload_context, filename):
    middleware, directory, context = upload_context
    files = [{"filename": filename}, {"filename": "current.md", "size": 24}]
    original = deepcopy(files)
    message = _gateway_message(files)
    assert message.additional_kwargs["files"] == files

    result = middleware.before_agent({"messages": [message]}, SimpleNamespace(context=context))

    assert [file["filename"] for file in result["uploaded_files"]] == ["current.md"]
    assert "# Current document" not in message.content
    assert "Current document" in project_upload_context(result["messages"][-1]).content
    assert message.additional_kwargs["files"] == original
    assert result["messages"][-1].additional_kwargs[ORIGINAL_USER_CONTENT_KEY] == "Read the attachment"


@pytest.mark.parametrize("filename", ["bad\x00.md", "../current.md", "/current.md", ".upload-active.part"])
@pytest.mark.parametrize("check_disk", [True, False])
def test_unusable_filename_is_skipped_before_filesystem_access(upload_context, monkeypatch, filename, check_disk):
    middleware, directory, _context = upload_context
    original_is_file = Path.is_file

    def guarded_is_file(path):
        if path.name != "current.md":
            pytest.fail("an unusable reference must not probe the filesystem")
        return original_is_file(path)

    monkeypatch.setattr(Path, "is_file", guarded_is_file)
    files = [{"filename": filename}, {"filename": "current.md"}]
    result = middleware._files_from_kwargs(_gateway_message(files), directory if check_disk else None)
    assert [file["filename"] for file in result] == ["current.md"]


@pytest.mark.parametrize("size", [10**400, "1" + "0" * 400, 10**4000], ids=["integer", "numeric-string", "long-integer"])
def test_parseable_size_cannot_overflow_context_rendering(upload_context, size):
    middleware, _directory, context = upload_context
    message = _gateway_message([{"filename": "current.md", "size": size}])

    result = middleware.before_agent({"messages": [message]}, SimpleNamespace(context=context))

    assert result["uploaded_files"][0]["size"] == 0
    assert "current.md (0.0 KB)" in project_upload_context(result["messages"][-1]).content
    assert "Current document" in project_upload_context(result["messages"][-1]).content


@pytest.mark.parametrize("size", [1024**4, 1024**4 + 1, 10**308], ids=["display-boundary", "above-boundary", "huge-finite"])
def test_large_renderable_size_keeps_metadata_with_a_bounded_display(upload_context, size):
    middleware, _directory, context = upload_context
    message = _gateway_message([{"filename": "current.md", "size": size}])
    result = middleware.before_agent({"messages": [message]}, SimpleNamespace(context=context))
    assert result["uploaded_files"][0]["size"] == size
    assert "current.md (>= 1 TB)" in project_upload_context(result["messages"][-1]).content
    assert message.additional_kwargs["files"][0]["size"] == size


@pytest.mark.parametrize("error", [PermissionError("unreadable"), OSError("file unavailable"), ValueError("invalid path")])
def test_file_probe_failure_does_not_drop_a_valid_sibling(upload_context, monkeypatch, caplog, error):
    middleware, directory, context = upload_context
    original_is_file = Path.is_file

    def unavailable(path):
        if path.name == "unavailable.md":
            raise error
        return original_is_file(path)

    monkeypatch.setattr(Path, "is_file", unavailable)
    message = _gateway_message([{"filename": "unavailable.md"}, {"filename": "current.md"}])
    with caplog.at_level(logging.DEBUG, logger="deerflow.agents.middlewares.uploads_middleware"):
        result = middleware.before_agent({"messages": [message]}, SimpleNamespace(context=context))
    assert [file["filename"] for file in result["uploaded_files"]] == ["current.md"]
    assert "unavailable.md" not in project_upload_context(result["messages"][-1]).content
    dropped = [record for record in caplog.records if "unavailable.md" in record.getMessage()]
    assert len(dropped) == 1
    assert dropped[0].levelno == logging.DEBUG
    assert type(error).__name__ in dropped[0].getMessage()
    assert str(error) in dropped[0].getMessage()


def test_unexpected_probe_error_is_not_silenced(upload_context, monkeypatch):
    middleware, directory, _context = upload_context

    def unexpected(_path):
        raise RuntimeError("implementation bug")

    monkeypatch.setattr(Path, "is_file", unexpected)
    with pytest.raises(RuntimeError, match="implementation bug"):
        middleware._files_from_kwargs(_gateway_message([{"filename": "current.md"}]), directory)


def test_all_invalid_metadata_clears_stale_current_uploads(upload_context):
    middleware, _directory, context = upload_context
    message = _gateway_message([{"filename": True}, {"filename": "bad\x00.md"}])
    state = {"messages": [message], "uploaded_files": [{"filename": "historical.md"}]}
    assert middleware.before_agent(state, SimpleNamespace(context=context)) == {"uploaded_files": []}
    assert message.content == "Read the attachment"


@pytest.mark.skipif(os.name == "nt", reason="Names legal on POSIX but not Windows")
@pytest.mark.parametrize("filename", ["CON.md", "report.md "])
def test_existing_posix_upload_names_are_not_rewritten(upload_context, filename):
    middleware, directory, _context = upload_context
    (directory / filename).write_text("Existing upload", encoding="utf-8")
    result = middleware._files_from_kwargs(_gateway_message([{"filename": filename}]), directory)
    assert result[0]["filename"] == filename
    assert result[0]["path"] == f"/mnt/user-data/uploads/{filename}"


def test_historical_discovery_only_excludes_admitted_current_files(upload_context):
    middleware, _directory, context = upload_context
    message = _gateway_message([{"filename": {"name": "historical.md"}}, {"filename": "current.md"}])
    update = middleware.before_agent({"messages": [message]}, SimpleNamespace(context=context))
    runtime = SimpleNamespace(context=context, state=update)
    listing = _list_uploaded_files_impl(runtime=runtime, _paths=middleware._paths)
    assert [file["filename"] for file in listing["files"]] == ["historical.md"]
    runtime.state = middleware.before_agent({"messages": [HumanMessage(content="Continue")]}, runtime)
    listing = _list_uploaded_files_impl(runtime=runtime, _paths=middleware._paths)
    assert {file["filename"] for file in listing["files"]} == {"current.md", "historical.md"}


class _UploadModel(FakeMessagesListChatModel):
    seen_messages: list[list[BaseMessage]] = Field(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen_messages.append(deepcopy(messages))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("invoke_async", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("size,size_label", [("1" + "0" * 400, "0.0 KB"), (10**308, ">= 1 TB")], ids=["overflowing", "huge-finite"])
async def test_agent_graph_consumes_only_valid_owner_upload_context(upload_context, invoke_async, size, size_label):
    middleware, _directory, context = upload_context
    other_directory = middleware._paths.sandbox_uploads_dir("upload-thread", user_id="bob")
    other_directory.mkdir(parents=True)
    (other_directory / "other-owner.md").write_text("# Private other-owner evidence", encoding="utf-8")
    model = _UploadModel(responses=[AIMessage(content="Processed")])
    agent = create_agent(model=model, tools=[], middleware=[InputSanitizationMiddleware(), middleware])
    message = _gateway_message(
        [{"filename": 42}, {"filename": "current.md", "size": size}, {"filename": "other-owner.md"}],
    )

    state = {"messages": [message]}
    config = {"configurable": {"thread_id": "upload-thread"}}
    if invoke_async:
        result = await agent.ainvoke(state, config, context=context)
    else:
        result = await asyncio.to_thread(agent.invoke, state, config, context=context)

    assert result["messages"][-1].content == "Processed"
    assert [file["filename"] for file in result["uploaded_files"]] == ["current.md"]
    rendered = message_content_to_text(result["messages"][0].content)
    assert rendered == "Read the attachment"
    assert "Private other-owner evidence" not in rendered
    assert len(model.seen_messages) == 1
    model_input = message_content_to_text(model.seen_messages[0][0].content)
    assert f"current.md ({size_label})" in model_input
    assert "Current document" in model_input
    assert "Private other-owner evidence" not in model_input
    assert message.content == "Read the attachment"
