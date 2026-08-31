"""Regression test: tool args schemas must not emit Pydantic serialization warnings.

DeerFlow tools annotate their runtime parameter as ``Runtime``
(``deerflow.tools.types.Runtime`` = ``ToolRuntime[dict[str, Any], ThreadState]``)
so the LangChain tool framework injects the runtime automatically.
When the inner ``Runtime.context`` field is left as the unbound ``ContextT``
TypeVar (default ``None``), Pydantic's ``model_dump()`` on the auto-generated
args schema emits a ``PydanticSerializationUnexpectedValue`` warning on every
tool call because the actual context DeerFlow installs is a dict. Using the
``Runtime`` alias (which binds the context to ``dict[str, Any]``) keeps
Pydantic's serialization expectations aligned with reality.
"""

from __future__ import annotations

import inspect
import warnings
from unittest.mock import AsyncMock

import pytest
from langchain.tools import ToolRuntime
from langchain_core.utils.function_calling import convert_to_openai_tool

from deerflow.sandbox.tools import (
    bash_tool,
    glob_tool,
    grep_tool,
    ls_tool,
    read_file_tool,
    str_replace_tool,
    write_file_tool,
)
from deerflow.tools.builtins.list_uploaded_files_tool import list_uploaded_files
from deerflow.tools.builtins.present_file_tool import present_file_tool
from deerflow.tools.builtins.setup_agent_tool import setup_agent
from deerflow.tools.builtins.task_tool import task_tool
from deerflow.tools.builtins.update_agent_tool import update_agent
from deerflow.tools.builtins.view_image_tool import view_image_tool
from deerflow.tools.skill_manage_tool import skill_manage_tool


def _make_runtime(context: dict) -> ToolRuntime:
    return ToolRuntime(
        state={"sandbox": {"sandbox_id": "local"}, "thread_data": {}},
        context=context,
        config={"configurable": {"thread_id": context.get("thread_id", "thread-1")}},
        stream_writer=lambda _: None,
        tools=[],
        tool_call_id="call-1",
        store=None,
    )


_TOOL_CASES = [
    (bash_tool, {"description": "list", "command": "ls"}),
    (ls_tool, {"description": "list", "path": "/tmp"}),
    (glob_tool, {"description": "find", "pattern": "*.py", "path": "/tmp"}),
    (grep_tool, {"description": "search", "pattern": "x", "path": "/tmp"}),
    (read_file_tool, {"description": "read", "path": "/tmp/x"}),
    (write_file_tool, {"description": "write", "path": "/tmp/x", "content": "hi"}),
    (str_replace_tool, {"description": "replace", "path": "/tmp/x", "old_str": "a", "new_str": "b"}),
    (list_uploaded_files, {"include_outline": False, "max_results": 20}),
    (present_file_tool, {"filepaths": ["/tmp/x"], "tool_call_id": "call-1"}),
    (view_image_tool, {"image_path": "/tmp/img.png", "tool_call_id": "call-1"}),
    (task_tool, {"description": "do", "prompt": "go", "subagent_type": "general-purpose", "tool_call_id": "call-1"}),
    (skill_manage_tool, {"action": "list", "name": "demo"}),
    (setup_agent, {"soul": "s", "description": "d"}),
    (update_agent, {}),
]

_SANDBOX_TOOL_CASES = [
    (bash_tool, {"command": "ls"}, ("command",), ("command", "description")),
    (ls_tool, {"path": "/tmp"}, ("path",), ("path", "description")),
    (
        glob_tool,
        {"pattern": "*.py", "path": "/tmp"},
        ("pattern", "path"),
        ("pattern", "path", "description", "include_dirs", "max_results"),
    ),
    (
        grep_tool,
        {"pattern": "x", "path": "/tmp"},
        ("pattern", "path"),
        ("pattern", "path", "description", "glob", "literal", "case_sensitive", "max_results"),
    ),
    (
        read_file_tool,
        {"path": "/tmp/x"},
        ("path",),
        ("path", "description", "start_line", "end_line"),
    ),
    (
        write_file_tool,
        {"path": "/tmp/x", "content": "hi"},
        ("path", "content"),
        ("path", "content", "description", "append"),
    ),
    (
        str_replace_tool,
        {"path": "/tmp/x", "old_str": "a", "new_str": "b"},
        ("path", "old_str", "new_str"),
        ("path", "old_str", "new_str", "description", "replace_all"),
    ),
]

_SANDBOX_TOOL_FORWARDING_CASES = [
    (bash_tool, {"command": "command", "description": "description"}, ("command", "description")),
    (ls_tool, {"path": "/path", "description": "description"}, ("/path", "description")),
    (
        glob_tool,
        {"pattern": "*.py", "path": "/path", "description": "description", "include_dirs": True, "max_results": 7},
        ("*.py", "/path", "description", True, 7),
    ),
    (
        grep_tool,
        {
            "pattern": "needle",
            "path": "/path",
            "description": "description",
            "glob": "*.py",
            "literal": True,
            "case_sensitive": True,
            "max_results": 7,
        },
        ("needle", "/path", "description", "*.py", True, True, 7),
    ),
    (
        read_file_tool,
        {"path": "/path", "description": "description", "start_line": 2, "end_line": 3},
        ("/path", "description", 2, 3),
    ),
    (
        write_file_tool,
        {"path": "/path", "content": "content", "description": "description", "append": True},
        ("/path", "content", "description", True),
    ),
    (
        str_replace_tool,
        {
            "path": "/path",
            "old_str": "old",
            "new_str": "new",
            "description": "description",
            "replace_all": True,
        },
        ("/path", "old", "new", "description", True),
    ),
]


@pytest.mark.parametrize(
    ("tool_obj", "extra_args"),
    _TOOL_CASES,
    ids=[case[0].name for case in _TOOL_CASES],
)
def test_tool_args_schema_does_not_emit_pydantic_context_warning(tool_obj, extra_args) -> None:
    """``model_dump()`` of the auto-generated args_schema must not warn about ``context``.

    The model_dump path is hit by LangChain's ``BaseTool._parse_input`` on every tool
    invocation (see langchain_core/tools/base.py:712), so any warning here would fire
    once per tool call and pollute production logs.
    """
    schema = tool_obj.args_schema
    assert schema is not None, f"{tool_obj.name} has no args_schema"

    runtime_obj = _make_runtime({"thread_id": "thread-1", "sandbox_id": "local"})
    payload = {**extra_args, "runtime": runtime_obj}

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        validated = schema.model_validate(payload)
        validated.model_dump()

    pydantic_warnings = [w for w in caught if "PydanticSerializationUnexpectedValue" in str(w.message)]
    assert not pydantic_warnings, f"{tool_obj.name} args_schema.model_dump() emitted Pydantic context serialization warnings: {[str(w.message) for w in pydantic_warnings]}"


def test_write_file_append_is_discoverable_in_tool_schema() -> None:
    """``append`` must be visible and described in the model-facing tool schema."""
    assert "append" in write_file_tool.description

    append_field = write_file_tool.tool_call_schema.model_fields["append"]
    assert append_field.default is False
    assert append_field.description
    assert "append" in append_field.description


@pytest.mark.parametrize(
    ("tool_obj", "operational_args", "required_args", "property_args"),
    _SANDBOX_TOOL_CASES,
    ids=[case[0].name for case in _SANDBOX_TOOL_CASES],
)
def test_sandbox_tool_description_is_optional_but_discoverable(tool_obj, operational_args, required_args, property_args) -> None:
    """Provider tool calls may omit UI-only descriptions without blocking execution."""
    parameters = convert_to_openai_tool(tool_obj)["function"]["parameters"]

    assert parameters["required"] == list(required_args)
    assert list(parameters["properties"]) == list(property_args)
    assert parameters["properties"]["description"]["description"]

    validated = tool_obj.tool_call_schema.model_validate(operational_args)
    assert validated.description == ""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_obj", "call_args", "forwarded_args"),
    _SANDBOX_TOOL_FORWARDING_CASES,
    ids=[case[0].name for case in _SANDBOX_TOOL_FORWARDING_CASES],
)
async def test_sandbox_tool_sync_async_signatures_and_forwarding_stay_aligned(
    monkeypatch,
    tool_obj,
    call_args,
    forwarded_args,
) -> None:
    """Async wrappers must keep both their public signature and positional forwarding aligned."""
    assert tool_obj.func is not None
    assert tool_obj.coroutine is not None
    assert list(inspect.signature(tool_obj.func).parameters) == list(inspect.signature(tool_obj.coroutine).parameters)

    run_sync_tool = AsyncMock(return_value="forwarded")
    monkeypatch.setattr("deerflow.sandbox.tools._run_sync_tool_after_async_sandbox_init", run_sync_tool)
    runtime = object()

    assert await tool_obj.coroutine(runtime=runtime, **call_args) == "forwarded"
    run_sync_tool.assert_awaited_once_with(tool_obj.func, runtime, *forwarded_args)

    run_sync_tool.reset_mock()
    call_args_without_description = {key: value for key, value in call_args.items() if key != "description"}
    forwarded_without_description = tuple("" if value == "description" else value for value in forwarded_args)

    assert await tool_obj.coroutine(runtime=runtime, **call_args_without_description) == "forwarded"
    run_sync_tool.assert_awaited_once_with(tool_obj.func, runtime, *forwarded_without_description)


def test_task_tool_description_is_optional_but_discoverable() -> None:
    """Subagent execution may not depend on its UI-only progress label."""
    parameters = convert_to_openai_tool(task_tool)["function"]["parameters"]

    assert parameters["required"] == ["prompt", "subagent_type"]
    assert list(parameters["properties"]) == ["prompt", "subagent_type", "acceptance_criteria", "description"]
    assert parameters["properties"]["description"]["description"]

    validated = task_tool.tool_call_schema.model_validate({"prompt": "go", "subagent_type": "general-purpose"})
    assert validated.description == ""


def test_list_uploaded_files_model_schema_excludes_injected_runtime() -> None:
    """The model-facing schema must not expose ToolRuntime internals."""
    parameters = convert_to_openai_tool(list_uploaded_files)["function"]["parameters"]

    assert set(parameters["properties"]) == {"include_outline", "max_results"}


@pytest.mark.parametrize("tool_obj", [case[0] for case in _TOOL_CASES], ids=[case[0].name for case in _TOOL_CASES])
def test_model_facing_tool_parameters_have_descriptions(tool_obj) -> None:
    """Every model-facing tool parameter should explain when and how to use it."""
    missing_descriptions = [field_name for field_name, field in tool_obj.tool_call_schema.model_fields.items() if not field.description]
    assert missing_descriptions == [], f"{tool_obj.name} has model-facing parameters without descriptions: {missing_descriptions}. Add an Args: section to the tool's docstring and ensure @tool(parse_docstring=True) is set."
