"""Live integration tests for DeerFlowClient with real API.

These tests require a working config.yaml with valid API credentials.
They are skipped in CI and must be run explicitly:

    PYTHONPATH=. uv run pytest tests/test_client_live.py -v -s
"""

import json
import os
import tempfile
from pathlib import Path

import pytest

# Skip entire module in CI or when no config.yaml exists
_skip_reason = None
if os.environ.get("CI"):
    _skip_reason = "Live tests skipped in CI"
elif not Path(__file__).resolve().parents[2].joinpath("config.yaml").exists():
    _skip_reason = "No config.yaml found — live tests require valid API credentials"

if _skip_reason:
    pytest.skip(_skip_reason, allow_module_level=True)

from src.client import DeerFlowClient, StreamEvent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    """Create a real DeerFlowClient (no mocks)."""
    return DeerFlowClient(thinking_enabled=False)


@pytest.fixture
def thread_tmp(tmp_path):
    """Provide a unique thread_id + tmp directory for file operations."""
    import uuid
    tid = f"live-test-{uuid.uuid4().hex[:8]}"
    return tid, tmp_path


# ===========================================================================
# Scenario 1: Basic chat — model responds coherently
# ===========================================================================

class TestLiveBasicChat:
    def test_chat_returns_nonempty_string(self, client):
        """chat() returns a non-empty response from the real model."""
        response = client.chat("Reply with exactly: HELLO")
        assert isinstance(response, str)
        assert len(response) > 0
        print(f"  chat response: {response}")

    def test_chat_follows_instruction(self, client):
        """Model can follow a simple instruction."""
        response = client.chat("What is 7 * 8? Reply with just the number.")
        assert "56" in response
        print(f"  math response: {response}")


# ===========================================================================
# Scenario 2: Streaming — events arrive in correct order
# ===========================================================================

class TestLiveStreaming:
    def test_stream_yields_message_and_done(self, client):
        """stream() produces at least one message event and ends with done."""
        events = list(client.stream("Say hi in one word."))

        types = [e.type for e in events]
        assert "message" in types, f"Expected 'message' event, got: {types}"
        assert types[-1] == "done"

        for e in events:
            assert isinstance(e, StreamEvent)
            print(f"  [{e.type}] {e.data}")

    def test_stream_message_content_nonempty(self, client):
        """Streamed message events contain non-empty content."""
        messages = [
            e for e in client.stream("What color is the sky? One word.")
            if e.type == "message"
        ]
        assert len(messages) >= 1
        for m in messages:
            assert len(m.data.get("content", "")) > 0


# ===========================================================================
# Scenario 3: Tool use — agent calls a tool and returns result
# ===========================================================================

class TestLiveToolUse:
    def test_agent_uses_bash_tool(self, client):
        """Agent uses bash tool when asked to run a command."""
        events = list(client.stream(
            "Use the bash tool to run: echo 'LIVE_TEST_OK'. "
            "Then tell me the output."
        ))

        types = [e.type for e in events]
        print(f"  event types: {types}")
        for e in events:
            print(f"  [{e.type}] {e.data}")

        # Should have tool_call + tool_result + message
        assert "tool_call" in types, f"Expected tool_call, got: {types}"
        assert "tool_result" in types, f"Expected tool_result, got: {types}"
        assert "message" in types

        tc = next(e for e in events if e.type == "tool_call")
        assert tc.data["name"] == "bash"

        tr = next(e for e in events if e.type == "tool_result")
        assert "LIVE_TEST_OK" in tr.data["content"]

    def test_agent_uses_ls_tool(self, client):
        """Agent uses ls tool to list a directory."""
        events = list(client.stream(
            "Use the ls tool to list the contents of /mnt/user-data/workspace. "
            "Just report what you see."
        ))

        types = [e.type for e in events]
        print(f"  event types: {types}")

        assert "tool_call" in types
        tc = next(e for e in events if e.type == "tool_call")
        assert tc.data["name"] == "ls"


# ===========================================================================
# Scenario 4: Multi-tool chain — agent chains tools in sequence
# ===========================================================================

class TestLiveMultiToolChain:
    def test_write_then_read(self, client):
        """Agent writes a file, then reads it back."""
        events = list(client.stream(
            "Step 1: Use write_file to write 'integration_test_content' to "
            "/mnt/user-data/outputs/live_test.txt. "
            "Step 2: Use read_file to read that file back. "
            "Step 3: Tell me the content you read."
        ))

        types = [e.type for e in events]
        print(f"  event types: {types}")
        for e in events:
            print(f"  [{e.type}] {e.data}")

        tool_calls = [e for e in events if e.type == "tool_call"]
        tool_names = [tc.data["name"] for tc in tool_calls]

        assert "write_file" in tool_names, f"Expected write_file, got: {tool_names}"
        assert "read_file" in tool_names, f"Expected read_file, got: {tool_names}"

        # Final message should mention the content
        messages = [e for e in events if e.type == "message"]
        final_text = messages[-1].data["content"] if messages else ""
        assert "integration_test_content" in final_text.lower() or any(
            "integration_test_content" in e.data.get("content", "")
            for e in events if e.type == "tool_result"
        )


# ===========================================================================
# Scenario 5: File upload lifecycle with real filesystem
# ===========================================================================

class TestLiveFileUpload:
    def test_upload_list_delete(self, client, thread_tmp):
        """Upload → list → delete → verify deletion."""
        thread_id, tmp_path = thread_tmp

        # Create test files
        f1 = tmp_path / "test_upload_a.txt"
        f1.write_text("content A")
        f2 = tmp_path / "test_upload_b.txt"
        f2.write_text("content B")

        # Upload
        results = client.upload_files(thread_id, [f1, f2])
        assert len(results) == 2
        filenames = {r["filename"] for r in results}
        assert filenames == {"test_upload_a.txt", "test_upload_b.txt"}
        for r in results:
            assert r["size"] > 0
            assert r["virtual_path"].startswith("/mnt/user-data/uploads/")
        print(f"  uploaded: {filenames}")

        # List
        listed = client.list_uploads(thread_id)
        assert len(listed) == 2
        print(f"  listed: {[f['filename'] for f in listed]}")

        # Delete one
        client.delete_upload(thread_id, "test_upload_a.txt")
        remaining = client.list_uploads(thread_id)
        assert len(remaining) == 1
        assert remaining[0]["filename"] == "test_upload_b.txt"
        print(f"  after delete: {[f['filename'] for f in remaining]}")

        # Delete the other
        client.delete_upload(thread_id, "test_upload_b.txt")
        assert client.list_uploads(thread_id) == []

    def test_upload_nonexistent_file_raises(self, client):
        with pytest.raises(FileNotFoundError):
            client.upload_files("t-fail", ["/nonexistent/path/file.txt"])


# ===========================================================================
# Scenario 6: Configuration query — real config loading
# ===========================================================================

class TestLiveConfigQueries:
    def test_list_models_returns_ark(self, client):
        """list_models() returns the configured ARK model."""
        models = client.list_models()
        assert len(models) >= 1
        names = [m["name"] for m in models]
        assert "ark-model" in names
        print(f"  models: {names}")

    def test_get_model_found(self, client):
        """get_model() returns details for existing model."""
        model = client.get_model("ark-model")
        assert model is not None
        assert model["name"] == "ark-model"
        print(f"  model detail: {model}")

    def test_get_model_not_found(self, client):
        assert client.get_model("nonexistent-model-xyz") is None

    def test_list_skills(self, client):
        """list_skills() runs without error."""
        skills = client.list_skills()
        assert isinstance(skills, list)
        print(f"  skills count: {len(skills)}")
        for s in skills[:3]:
            print(f"    - {s['name']}: {s['enabled']}")


# ===========================================================================
# Scenario 7: Artifact read after agent writes
# ===========================================================================

class TestLiveArtifact:
    def test_get_artifact_after_write(self, client):
        """Agent writes a file → client reads it back via get_artifact()."""
        import uuid
        thread_id = f"live-artifact-{uuid.uuid4().hex[:8]}"

        # Ask agent to write a file
        events = list(client.stream(
            "Use write_file to create /mnt/user-data/outputs/artifact_test.json "
            "with content: {\"status\": \"ok\", \"source\": \"live_test\"}",
            thread_id=thread_id,
        ))

        # Verify write happened
        tool_calls = [e for e in events if e.type == "tool_call"]
        assert any(tc.data["name"] == "write_file" for tc in tool_calls)

        # Read artifact
        content, mime = client.get_artifact(thread_id, "mnt/user-data/outputs/artifact_test.json")
        data = json.loads(content)
        assert data["status"] == "ok"
        assert data["source"] == "live_test"
        assert "json" in mime
        print(f"  artifact: {data}, mime: {mime}")

    def test_get_artifact_not_found(self, client):
        with pytest.raises(FileNotFoundError):
            client.get_artifact("nonexistent-thread", "mnt/user-data/outputs/nope.txt")


# ===========================================================================
# Scenario 8: Per-call overrides
# ===========================================================================

class TestLiveOverrides:
    def test_thinking_disabled_still_works(self, client):
        """Explicit thinking_enabled=False override produces a response."""
        response = client.chat(
            "Say OK.", thinking_enabled=False,
        )
        assert len(response) > 0
        print(f"  response: {response}")


# ===========================================================================
# Scenario 9: Error resilience
# ===========================================================================

class TestLiveErrorResilience:
    def test_delete_nonexistent_upload(self, client):
        with pytest.raises(FileNotFoundError):
            client.delete_upload("nonexistent-thread", "ghost.txt")

    def test_bad_artifact_path(self, client):
        with pytest.raises(ValueError):
            client.get_artifact("t", "invalid/path")

    def test_path_traversal_blocked(self, client):
        with pytest.raises(PermissionError):
            client.delete_upload("t", "../../etc/passwd")
