"""Offline regression and CLI probe for view_image sandbox authorization.

From ``backend/``::

    .venv/bin/python tests/test_view_image_sandbox_authorization_regression.py --expect vulnerable
    .venv/bin/python tests/test_view_image_sandbox_authorization_regression.py --expect blocked
    .venv/bin/python -m pytest tests/test_view_image_sandbox_authorization_regression.py -q

The probe uses one synthetic GIF in a temporary directory. It needs no server,
model provider, credentials, or network access.
"""

import argparse
import base64
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from langchain.agents.middleware.types import ModelRequest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from deerflow.agents.middlewares.view_image_middleware import ViewImageMiddleware
from deerflow.authz.adapter import GuardrailAuthorizationAdapter
from deerflow.authz.rbac import RbacAuthorizationProvider
from deerflow.authz.sandbox_authz import authorize_sandbox_execution
from deerflow.authz.tool_filter import apply_tool_authorization
from deerflow.config.app_config import AppConfig
from deerflow.config.authorization_config import AuthorizationConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.paths import Paths
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.guardrails.provider import GuardrailRequest
from deerflow.sandbox.exceptions import SandboxAuthorizationError
from deerflow.tools.builtins.view_image_tool import view_image_tool

GIF_BYTES = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")
IMAGE_PATH = "/mnt/user-data/uploads/synthetic.gif"


def _setup(root: Path, monkeypatch: pytest.MonkeyPatch, *, sandbox_allowed: bool):
    context = {"thread_id": "synthetic-thread", "user_id": "synthetic-user", "user_role": "reviewer"}
    paths = Paths(root)
    thread_id, user_id = context["thread_id"], context["user_id"]
    uploads = paths.sandbox_uploads_dir(thread_id, user_id=user_id)
    uploads.mkdir(parents=True)
    image_file = uploads / "synthetic.gif"
    image_file.write_bytes(GIF_BYTES)
    runtime = SimpleNamespace(
        state={
            "thread_data": {
                "workspace_path": str(paths.sandbox_work_dir(thread_id, user_id=user_id)),
                "uploads_path": str(uploads),
                "outputs_path": str(paths.sandbox_outputs_dir(thread_id, user_id=user_id)),
            }
        },
        context=context,
        config={},
    )
    config = AppConfig(
        models=[ModelConfig(name="synthetic", model="synthetic", use="langchain_openai:ChatOpenAI", supports_vision=True)],
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
        authorization=AuthorizationConfig(enabled=True, fail_closed=True, default_role="reviewer"),
    )
    provider = RbacAuthorizationProvider(roles={"reviewer": {"tools": {"allow": ["view_image"]}, "sandbox": {"allow": sandbox_allowed}}})
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.authz.sandbox_authz.resolve_authorization_provider", lambda _: provider)
    authorized_tools, _ = apply_tool_authorization([view_image_tool], context=context, app_config=config, authorization_provider=provider)
    assert [tool.name for tool in authorized_tools] == ["view_image"]
    tool_decision = GuardrailAuthorizationAdapter(provider, default_role="reviewer").evaluate(
        GuardrailRequest(tool_name="view_image", tool_input={"image_path": IMAGE_PATH}, thread_id=context["thread_id"], user_id=context["user_id"], user_role=context["user_role"])
    )
    assert tool_decision.allow
    return runtime, config, image_file


def _model_request(runtime, viewed_images: dict, tool_message: ToolMessage | None = None) -> ModelRequest:
    messages = [
        HumanMessage(content="Describe this synthetic image"),
        AIMessage(content="", tool_calls=[{"name": "view_image", "args": {"image_path": IMAGE_PATH}, "id": "image-call"}]),
        tool_message or ToolMessage(content="Successfully read image", tool_call_id="image-call"),
    ]
    return ModelRequest(
        model=FakeMessagesListChatModel(responses=[AIMessage(content="ok")]),
        messages=messages,
        system_message=None,
        tool_choice=None,
        tools=[],
        response_format=None,
        state={"messages": messages, "viewed_images": viewed_images, "thread_data": runtime.state["thread_data"]},
        runtime=SimpleNamespace(context=runtime.context),
        model_settings={},
    )


def _image_payloads(request: ModelRequest) -> list[dict]:
    return [block for message in request.messages for block in (message.content if isinstance(message.content, list) else []) if isinstance(block, dict) and block.get("type") == "image_url"]


def _image_metadata(image_file: Path) -> dict:
    return {IMAGE_PATH: {"actual_path": str(image_file), "mime_type": "image/gif", "size": len(GIF_BYTES)}}


def test_allowed_sync_read_still_reaches_model(tmp_path, monkeypatch):
    runtime, config, _ = _setup(tmp_path, monkeypatch, sandbox_allowed=True)
    authorize_sandbox_execution(context=runtime.context, app_config=config)
    result = view_image_tool.func(runtime=runtime, image_path=IMAGE_PATH, tool_call_id="image-call")
    assert result.update["messages"][0].content == "Successfully read image"
    request = ViewImageMiddleware()._inject(_model_request(runtime, result.update["viewed_images"], result.update["messages"][0]))
    assert _image_payloads(request)[0]["image_url"]["url"] == f"data:image/gif;base64,{base64.b64encode(GIF_BYTES).decode()}"


def test_denied_sync_tool_stops_before_image_read(tmp_path, monkeypatch):
    runtime, config, image_file = _setup(tmp_path, monkeypatch, sandbox_allowed=False)
    with pytest.raises(SandboxAuthorizationError):
        authorize_sandbox_execution(context=runtime.context, app_config=config)
    original_open = open
    reads = []

    def record_open(file, *args, **kwargs):
        if isinstance(file, (str, bytes, Path)) and Path(file).resolve() == image_file.resolve():
            reads.append(file)
        return original_open(file, *args, **kwargs)

    with patch("builtins.open", side_effect=record_open):
        with pytest.raises(SandboxAuthorizationError):
            view_image_tool.func(runtime=runtime, image_path=IMAGE_PATH, tool_call_id="image-call")
    assert reads == []


def test_denied_restored_view_does_not_reenter_model(tmp_path, monkeypatch):
    runtime, _, _ = _setup(tmp_path, monkeypatch, sandbox_allowed=True)
    viewed = view_image_tool.func(runtime=runtime, image_path=IMAGE_PATH, tool_call_id="image-call").update["viewed_images"]
    denied_provider = RbacAuthorizationProvider(roles={"reviewer": {"tools": {"allow": ["view_image"]}, "sandbox": {"allow": False}}})
    monkeypatch.setattr("deerflow.authz.sandbox_authz.resolve_authorization_provider", lambda _: denied_provider)
    stranded = ViewImageMiddleware._create_image_context_message([{"type": "image_url", "image_url": {"url": "data:image/gif;base64,stale"}}])
    original_request = _model_request(runtime, viewed)
    original_request = original_request.override(messages=[*original_request.messages, stranded])
    with patch("builtins.open", side_effect=AssertionError("denied image read")):
        request = ViewImageMiddleware()._inject(original_request)
    assert _image_payloads(request) == []
    assert stranded not in request.messages


def test_denied_tool_does_not_touch_live_sandbox(tmp_path, monkeypatch):
    runtime, _, _ = _setup(tmp_path, monkeypatch, sandbox_allowed=False)
    runtime.state["sandbox"] = {"sandbox_id": "synthetic-remote"}
    with patch("deerflow.sandbox.sandbox_provider.get_sandbox_provider", side_effect=AssertionError("denied sandbox lookup")):
        with pytest.raises(SandboxAuthorizationError):
            view_image_tool.func(runtime=runtime, image_path=IMAGE_PATH, tool_call_id="image-call")


@pytest.mark.asyncio
async def test_denied_async_tool_and_restored_view_do_not_read(tmp_path, monkeypatch):
    runtime, _, image_file = _setup(tmp_path, monkeypatch, sandbox_allowed=False)
    stale_context = ViewImageMiddleware._create_image_context_message([{"type": "image_url", "image_url": {"url": "data:image/gif;base64,stale"}}])
    user_message = HumanMessage(id="view-image-context:user-authored", content="Keep this message")
    original_request = _model_request(runtime, _image_metadata(image_file))
    original_request = original_request.override(messages=[*original_request.messages, stale_context, user_message])
    with patch("builtins.open", side_effect=AssertionError("denied image read")):
        with pytest.raises(SandboxAuthorizationError):
            await view_image_tool.coroutine(runtime=runtime, image_path=IMAGE_PATH, tool_call_id="image-call")

        async def handler(request):
            return request

        request = await ViewImageMiddleware().awrap_model_call(original_request, handler)
    assert _image_payloads(request) == []
    assert stale_context not in request.messages
    assert user_message in request.messages


@pytest.mark.asyncio
async def test_allowed_async_tool_and_model_injection(tmp_path, monkeypatch):
    runtime, _, _ = _setup(tmp_path, monkeypatch, sandbox_allowed=True)
    result = await view_image_tool.coroutine(runtime=runtime, image_path=IMAGE_PATH, tool_call_id="image-call")

    async def handler(request):
        return request

    request = await ViewImageMiddleware().awrap_model_call(_model_request(runtime, result.update["viewed_images"], result.update["messages"][0]), handler)
    assert len(_image_payloads(request)) == 1


def _run_probe() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="deerflow-image-authz-") as temp_dir, pytest.MonkeyPatch.context() as monkeypatch:
        runtime, config, image_file = _setup(Path(temp_dir), monkeypatch, sandbox_allowed=False)
        with pytest.raises(SandboxAuthorizationError):
            authorize_sandbox_execution(context=runtime.context, app_config=config)
        original_open = open
        image_reads = 0

        def record_open(file, *args, **kwargs):
            nonlocal image_reads
            if isinstance(file, (str, bytes, Path)) and Path(file).resolve() == image_file.resolve():
                image_reads += 1
            return original_open(file, *args, **kwargs)

        with patch("builtins.open", side_effect=record_open):
            try:
                result = view_image_tool.func(runtime=runtime, image_path=IMAGE_PATH, tool_call_id="image-call")
            except SandboxAuthorizationError:
                tool_denied = True
                viewed_images = {}
            else:
                tool_denied = False
                viewed_images = result.update.get("viewed_images", {})
            request = ViewImageMiddleware()._inject(_model_request(runtime, viewed_images or _image_metadata(image_file)))
        return {"tool_denied": tool_denied, "sandbox_denied": True, "image_reads": image_reads, "model_received_image": bool(_image_payloads(request))}


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--expect", choices=("vulnerable", "blocked"), required=True)
    args = parser.parse_args()
    observed = _run_probe()
    vulnerable = not observed["tool_denied"] and observed["image_reads"] >= 2 and observed["model_received_image"]
    blocked = observed["tool_denied"] and observed["image_reads"] == 0 and not observed["model_received_image"]
    status = "vulnerable" if vulnerable else "blocked" if blocked else "inconclusive"
    print(json.dumps({**observed, "observed": status, "expected": args.expect}, sort_keys=True))
    return 0 if status == args.expect else 2


if __name__ == "__main__":
    raise SystemExit(_main())
