from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from deerflow.agents.middlewares.artifact_capture_middleware import ArtifactCaptureMiddleware
from deerflow.config.tool_artifact_config import ToolArtifactConfig
from deerflow.tools.artifact_registry import generate_handle


def _runtime(thread_id: str = "thread_1"):
    return SimpleNamespace(context={"thread_id": thread_id})


def _tool_message(content: str, tool_call_id: str = "call_1", *, artifact: dict | None = None) -> ToolMessage:
    return ToolMessage(content=content, tool_call_id=tool_call_id, artifact=artifact)


class TestCapture:
    def test_captures_structured_artifact(self):
        middleware = ArtifactCaptureMiddleware()
        msg = _tool_message(
            "wrote file",
            artifact={"structured_content": {"file": "/mnt/user-data/outputs/report.md", "mime_type": "text/markdown"}},
        )
        out = middleware.before_model({"messages": [msg]}, _runtime())

        assert out is not None
        (entry,) = out["tool_artifacts"]
        assert entry["artifact_type"] == "data"
        assert entry["handle"].startswith("art_")

    def test_handle_deterministic_per_tool_call(self):
        middleware = ArtifactCaptureMiddleware()
        msg = _tool_message(
            "wrote file",
            artifact={"structured_content": {"file": "/mnt/user-data/outputs/report.md"}},
        )
        first = middleware.before_model({"messages": [msg]}, _runtime("thread_1"))
        second = middleware.before_model({"messages": [msg]}, _runtime("thread_1"))
        assert first["tool_artifacts"][0]["handle"] == second["tool_artifacts"][0]["handle"]

    def test_structured_preview_stored_as_real_ref(self):
        middleware = ArtifactCaptureMiddleware()
        msg = _tool_message(
            "wrote file",
            artifact={"structured_content": {"file": "/mnt/user-data/outputs/data.csv"}},
        )
        out = middleware.before_model({"messages": [msg]}, _runtime())

        assert out["tool_artifacts"][0]["real_ref"].startswith("{")

    def test_does_not_capture_twice(self):
        middleware = ArtifactCaptureMiddleware()
        msg = _tool_message(
            "wrote file",
            artifact={"structured_content": {"file": "/mnt/user-data/outputs/report.md"}},
        )
        state = {"messages": [msg], "tool_artifacts": []}
        first = middleware.before_model(state, _runtime())
        state["tool_artifacts"] = first["tool_artifacts"]
        second = middleware.before_model(state, _runtime())

        assert second is None

    def test_disabled_config_skips_capture(self):
        middleware = ArtifactCaptureMiddleware(config=ToolArtifactConfig(enabled=False))
        msg = _tool_message(
            "wrote file",
            artifact={"structured_content": {"file": "/mnt/user-data/outputs/report.md"}},
        )
        assert middleware.before_model({"messages": [msg]}, _runtime()) is None

    def test_tracks_consumption_of_handle_in_tool_args(self):
        middleware = ArtifactCaptureMiddleware()
        handle = generate_handle("thread_1", "call_1", 0)
        entry = {
            "handle": handle,
            "artifact_type": "file",
            "real_ref": "/mnt/user-data/outputs/report.md",
            "display_name": "report.md",
            "tool_name": "write_file",
            "mime_type": None,
            "consumed_by": [],
        }
        state = {
            "tool_artifacts": [entry],
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "read_file", "args": {"path": f"{handle}"}, "id": "call_2", "type": "tool_call"}
                    ],
                )
            ],
        }

        out = middleware.before_model(state, _runtime())

        assert out is not None
        assert out["tool_artifacts"][0]["consumed_by"] == ["call_2"]

    def test_no_update_when_no_handle_referenced(self):
        middleware = ArtifactCaptureMiddleware()
        entry = {
            "handle": generate_handle("thread_1", "call_1", 0),
            "artifact_type": "file",
            "real_ref": "/mnt/user-data/outputs/report.md",
            "display_name": "report.md",
            "tool_name": "write_file",
            "mime_type": None,
            "consumed_by": [],
        }
        state = {
            "tool_artifacts": [entry],
            "messages": [HumanMessage(content="hello")],
        }

        assert middleware.before_model(state, _runtime()) is None