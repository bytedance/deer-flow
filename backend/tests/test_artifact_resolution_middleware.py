from langchain_core.messages import ToolMessage

from deerflow.agents.middlewares.artifact_resolution_middleware import ArtifactResolutionMiddleware
from deerflow.config.tool_artifact_config import ToolArtifactConfig
from deerflow.tools.artifact_registry import generate_handle


class _FakeToolCallRequest:
    def __init__(self, tool_call: dict, state: dict) -> None:
        self.tool_call = tool_call
        self.state = state

    def override(self, **overrides):
        return _FakeToolCallRequest(
            overrides.get("tool_call", self.tool_call),
            overrides.get("state", self.state),
        )


def _request(tool_call: dict, artifacts: list[dict]):
    return _FakeToolCallRequest(tool_call, {"tool_artifacts": artifacts})


def _artifact(thread_id: str, call_index: int, real_ref: str) -> dict:
    return {
        "handle": generate_handle(thread_id, f"call_{call_index}", call_index),
        "artifact_type": "file",
        "real_ref": real_ref,
        "display_name": real_ref.rsplit("/", 1)[-1],
        "tool_name": "write_file",
        "mime_type": None,
        "consumed_by": [],
    }


class TestResolution:
    def test_resolves_bare_handle_in_args(self):
        middleware = ArtifactResolutionMiddleware()
        handle = generate_handle("thread_1", "call_0", 0)
        request = _request(
            {"name": "read_file", "args": {"path": handle}, "id": "call_2", "type": "tool_call"},
            [_artifact("thread_1", 0, "/mnt/user-data/outputs/report.md")],
        )
        seen = {}

        def handler(req):
            seen["args"] = req.tool_call["args"]
            return ToolMessage(content="ok", tool_call_id="call_2")

        result = middleware.wrap_tool_call(request, handler)

        assert seen["args"] == {"path": "/mnt/user-data/outputs/report.md"}
        assert result.content == "ok"

    def test_resolves_backticked_handle_in_args(self):
        middleware = ArtifactResolutionMiddleware()
        handle = generate_handle("thread_1", "call_0", 0)
        request = _request(
            {"name": "bash", "args": {"command": f"cat `{handle}`"}, "id": "call_2", "type": "tool_call"},
            [_artifact("thread_1", 0, "/mnt/user-data/outputs/report.md")],
        )
        seen = {}

        def handler(req):
            seen["args"] = req.tool_call["args"]
            return ToolMessage(content="ok", tool_call_id="call_2")

        middleware.wrap_tool_call(request, handler)

        assert seen["args"] == {"command": "cat /mnt/user-data/outputs/report.md"}

    def test_resolves_nested_handle(self):
        middleware = ArtifactResolutionMiddleware()
        handle = generate_handle("thread_1", "call_0", 0)
        request = _request(
            {
                "name": "bash",
                "args": {"command": "echo hi", "cwd": None, "files": [{"path": handle, "mode": "r"}]},
                "id": "call_2",
                "type": "tool_call",
            },
            [_artifact("thread_1", 0, "/mnt/user-data/outputs/report.md")],
        )
        seen = {}

        def handler(req):
            seen["args"] = req.tool_call["args"]
            return ToolMessage(content="ok", tool_call_id="call_2")

        middleware.wrap_tool_call(request, handler)

        assert seen["args"]["files"][0]["path"] == "/mnt/user-data/outputs/report.md"

    def test_unknown_handle_left_untouched(self):
        middleware = ArtifactResolutionMiddleware()
        request = _request(
            {"name": "read_file", "args": {"path": "art_00000000"}, "id": "call_2", "type": "tool_call"},
            [_artifact("thread_1", 0, "/mnt/user-data/outputs/report.md")],
        )
        seen = {}

        def handler(req):
            seen["args"] = req.tool_call["args"]
            return ToolMessage(content="ok", tool_call_id="call_2")

        middleware.wrap_tool_call(request, handler)

        assert seen["args"] == {"path": "art_00000000"}

    def test_no_artifacts_skips_resolution(self):
        middleware = ArtifactResolutionMiddleware()
        request = _request({"name": "read_file", "args": {"path": "art_00000000"}, "id": "call_2", "type": "tool_call"}, [])
        called = []

        def handler(req):
            called.append(req)
            return ToolMessage(content="ok", tool_call_id="call_2")

        result = middleware.wrap_tool_call(request, handler)

        assert called[0] is request
        assert result.content == "ok"

    def test_disabled_config_skips_resolution(self):
        middleware = ArtifactResolutionMiddleware(config=ToolArtifactConfig(resolve_handles_in_args=False))
        request = _request(
            {"name": "read_file", "args": {"path": "art_00000000"}, "id": "call_2", "type": "tool_call"},
            [_artifact("thread_1", 0, "/mnt/user-data/outputs/report.md")],
        )
        called = []

        def handler(req):
            called.append(req)
            return ToolMessage(content="ok", tool_call_id="call_2")

        middleware.wrap_tool_call(request, handler)

        assert called[0] is request