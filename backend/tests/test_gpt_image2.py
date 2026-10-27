import base64
import importlib
import io
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.tools import ToolException
from PIL import Image

from deerflow.config.paths import Paths
from deerflow.runtime.user_context import reset_current_user, set_current_user
from deerflow.security.store import UserSecurityStore


def png(size=(8, 8), mode="RGB"):
    out = io.BytesIO()
    Image.new(mode, size, "red").save(out, format="PNG")
    return out.getvalue()


@pytest.fixture
def env(tmp_path, monkeypatch):
    service = importlib.import_module("deerflow.community.gpt_image2.service")
    paths = Paths(tmp_path / "data")
    store = UserSecurityStore(paths.base_dir / "security")
    store.root.mkdir(parents=True)
    (store.root / "gpt_image2.key").write_text("company-key-do-not-echo", encoding="utf-8")
    config = SimpleNamespace(
        authorization=SimpleNamespace(enabled=True, provider=SimpleNamespace(use="deerflow.authz.user_policy:UserAuthorizationProvider", config={"store_path": str(store.root)})),
        get_tool_config=lambda name: SimpleNamespace(use="deerflow.community.gpt_image2.tools:gpt_image2_tool"),
    )
    monkeypatch.setattr(service, "get_app_config", lambda: config)
    monkeypatch.setattr(service, "get_paths", lambda: paths)
    token = set_current_user(SimpleNamespace(id="alice", system_role="user"))
    runtime = SimpleNamespace(context={"user_id": "alice", "user_role": "user", "thread_id": "thread-one"}, config={})
    calls = []
    response = {"data": [{"b64_json": base64.b64encode(png()).decode()}]}

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=response)

    monkeypatch.setattr(service, "_new_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    value = SimpleNamespace(service=service, paths=paths, store=store, runtime=runtime, calls=calls, response=response, config=config)
    try:
        yield value
    finally:
        reset_current_user(token)


def grant(env):
    env.store.set_grant("alice", "tool", "gpt_image2", True, actor="admin")


@pytest.mark.asyncio
async def test_requires_live_tool_grant_before_any_request_or_key_read(env):
    (env.store.root / "gpt_image2.key").unlink()
    with pytest.raises(ToolException, match="authorized"):
        await env.service.generate_image(env.runtime, "a tree")
    assert env.calls == []


@pytest.mark.asyncio
async def test_shared_key_generation_is_private_and_revocable(env):
    import json

    grant(env)
    output = await env.service.generate_image(env.runtime, "a tree", quality="low")
    assert output.startswith("/mnt/user-data/outputs/gpt-image2-")
    target = env.paths.resolve_virtual_path("thread-one", output, user_id="alice")
    assert target.read_bytes() == png()
    assert not env.paths.sandbox_outputs_dir("thread-one", user_id="bob").exists()
    request = env.calls[0]
    assert request.url == "https://api.openai.com/v1/images/generations"
    assert request.headers["Authorization"] == "Bearer company-key-do-not-echo"
    body = json.loads(request.content)
    assert body["model"] == "gpt-image-2" and body["n"] == 1 and body["output_format"] == "png"
    assert body["quality"] == "low"
    assert "company-key" not in output
    env.store.set_override("alice", "tool", "gpt_image2", "deny", actor="admin")
    with pytest.raises(ToolException, match="authorized"):
        await env.service.generate_image(env.runtime, "a tree")
    assert len(env.calls) == 1


@pytest.mark.asyncio
async def test_group_grant_and_admin_access(env):
    group = env.store.create_group("Design", actor="admin")
    env.store.set_member(group["id"], "alice", True, actor="admin")
    env.store.set_group_grant(group["id"], "tool", "gpt_image2", True, actor="admin")
    await env.service.generate_image(env.runtime, "a tree")
    env.store.delete_group(group["id"], actor="admin")
    token = set_current_user(SimpleNamespace(id="alice", system_role="admin"))
    try:
        env.runtime.context["user_role"] = "admin"
        await env.service.generate_image(env.runtime, "a tree")
    finally:
        reset_current_user(token)
    assert len(env.calls) == 2


@pytest.mark.asyncio
async def test_reference_edit_uses_only_owned_files_and_mask(env):
    grant(env)
    uploads = env.paths.sandbox_uploads_dir("thread-one", user_id="alice")
    uploads.mkdir(parents=True)
    (uploads / "ref.png").write_bytes(png())
    (uploads / "mask.png").write_bytes(png(mode="RGBA"))
    await env.service.generate_image(env.runtime, "make blue", reference_images=["/mnt/user-data/uploads/ref.png"], mask="/mnt/user-data/uploads/mask.png")
    request = env.calls[0]
    assert request.url.path == "/v1/images/edits"
    assert "multipart/form-data" in request.headers["content-type"]
    assert b'name="image[]"' in request.content and b'name="mask"' in request.content
    assert b"input_fidelity" not in request.content


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/etc/passwd", "/mnt/user-data/../../security/gpt_image2.key", "https://example.org/ref.png", "/mnt/user-data/uploads/missing.png"])
async def test_unsafe_and_missing_inputs_make_no_request(env, path):
    grant(env)
    with pytest.raises(ToolException):
        await env.service.generate_image(env.runtime, "a tree", reference_images=[path])
    assert not env.calls


@pytest.mark.asyncio
async def test_symlink_input_and_output_cannot_cross_owner(env):
    grant(env)
    root = env.paths.sandbox_user_data_dir("thread-one", user_id="alice")
    root.mkdir(parents=True)
    other = env.paths.sandbox_outputs_dir("other-thread", user_id="bob")
    other.mkdir(parents=True)
    (other / "private.png").write_bytes(png())
    (root / "uploads").symlink_to(other, target_is_directory=True)
    with pytest.raises(ToolException):
        await env.service.generate_image(env.runtime, "a tree", reference_images=["/mnt/user-data/uploads/private.png"])
    (root / "outputs").rmdir()
    (root / "outputs").symlink_to(other, target_is_directory=True)
    with pytest.raises(ToolException):
        await env.service.generate_image(env.runtime, "a tree")
    assert not env.calls
    assert sorted(p.name for p in other.iterdir()) == ["private.png"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [{"prompt": ""}, {"prompt": "x", "size": "999999x999999"}, {"prompt": "x", "quality": "invalid"}, {"prompt": "x", "mask": "/mnt/user-data/uploads/x.png"}, {"prompt": "x", "reference_images": ["x"] * 5}])
async def test_invalid_request_does_not_bill(env, kwargs):
    grant(env)
    with pytest.raises(ToolException):
        await env.service.generate_image(env.runtime, **kwargs)
    assert not env.calls


@pytest.mark.asyncio
async def test_conflicting_identity_fails_closed(env):
    grant(env)
    env.runtime.context["user_id"] = "bob"
    env.runtime.context["user_role"] = "admin"
    with pytest.raises(ToolException, match="identity"):
        await env.service.generate_image(env.runtime, "x")
    assert not env.calls


@pytest.mark.asyncio
async def test_remote_errors_are_redacted_and_never_retried(env, monkeypatch):
    grant(env)
    calls = []

    def error(request):
        calls.append(request)
        return httpx.Response(401, text="company-key-do-not-echo REMOTE-PRIVATE-BODY")

    monkeypatch.setattr(env.service, "_new_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(error)))
    with pytest.raises(ToolException) as exc:
        await env.service.generate_image(env.runtime, "x")
    assert "401" in str(exc.value)
    assert "company-key" not in str(exc.value) and "REMOTE-PRIVATE" not in str(exc.value)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_invalid_image_payload_is_not_published(env):
    grant(env)
    env.response["data"][0]["b64_json"] = base64.b64encode(b"not an image").decode()
    with pytest.raises(ToolException):
        await env.service.generate_image(env.runtime, "x")
    assert list(env.paths.sandbox_outputs_dir("thread-one", user_id="alice").glob("*.png")) == []


@pytest.mark.asyncio
async def test_timeout_is_not_retried_and_capacity_is_released(env, monkeypatch):
    grant(env)
    calls = []

    def timeout(request):
        calls.append(request)
        raise httpx.ReadTimeout("company-key-do-not-echo", request=request)

    monkeypatch.setattr(env.service, "_new_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(timeout)))
    with pytest.raises(ToolException, match="may have been billed") as exc:
        await env.service.generate_image(env.runtime, "x")
    assert "company-key" not in str(exc.value)
    assert len(calls) == 1
    assert env.service._CAPACITY.acquire(blocking=False)
    env.service._CAPACITY.release()


@pytest.mark.asyncio
async def test_response_limit_and_busy_never_retry(env, monkeypatch):
    grant(env)
    monkeypatch.setattr(env.service, "MAX_RESPONSE_BYTES", 8)
    with pytest.raises(ToolException, match="size limit"):
        await env.service.generate_image(env.runtime, "x")
    env.service._CAPACITY.acquire()
    env.service._CAPACITY.acquire()
    try:
        with pytest.raises(ToolException, match="busy"):
            await env.service.generate_image(env.runtime, "x")
    finally:
        env.service._CAPACITY.release()
        env.service._CAPACITY.release()
    assert len(env.calls) == 1


@pytest.mark.asyncio
async def test_native_tool_presents_artifact_and_never_exposes_key_in_schema(env):
    from deerflow.community.gpt_image2.tools import gpt_image2_tool

    grant(env)
    result = await gpt_image2_tool.coroutine(runtime=env.runtime, tool_call_id="image-call", prompt="a tree")
    assert len(result.update["artifacts"]) == 1
    assert result.update["messages"][0].tool_call_id == "image-call"
    assert "key" not in gpt_image2_tool.tool_call_schema.model_json_schema()["properties"]
    assert "company-key" not in str(result)


@pytest.mark.asyncio
async def test_langgraph_injects_runtime_and_merges_generated_artifact(env):
    from langchain_core.messages import AIMessage
    from langgraph.graph import END, START, StateGraph
    from langgraph.prebuilt import ToolNode

    from deerflow.agents.thread_state import ThreadState
    from deerflow.community.gpt_image2.tools import gpt_image2_tool

    grant(env)
    builder = StateGraph(ThreadState, context_schema=dict)
    builder.add_node("tools", ToolNode([gpt_image2_tool]))
    builder.add_edge(START, "tools")
    builder.add_edge("tools", END)
    result = await builder.compile().ainvoke(
        {"messages": [AIMessage(content="", tool_calls=[{"id": "graph-image", "name": "gpt_image2", "args": {"prompt": "a tree"}}])]},
        context=env.runtime.context,
    )
    assert len(result["artifacts"]) == 1
    assert result["messages"][-1].tool_call_id == "graph-image"
    assert len(env.calls) == 1
