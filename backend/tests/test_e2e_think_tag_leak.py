"""End-to-end test: <think> tag leakage via mock ollama + LangChain (#781).

This test starts a mock ollama server that returns <think> tags in the
content field (exactly how ollama serves DeepSeek-R1/QwQ), then calls
it through LangChain's ChatOpenAI (DeerFlow's actual model interface)
and runs the result through SubagentExecutor's content extraction logic.

This proves the bug exists in the real code path without needing
an actual ollama installation.
"""

import json
import pathlib
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_openai import ChatOpenAI

# ── Mock ollama server ────────────────────────────────────────────────

THINK_CONTENT = (
    "<think>\n"
    "The user is asking about 2+2. This is a basic arithmetic question.\n"
    "Let me verify: 2 + 2 = 4. Yes, that's correct.\n"
    "I should give a clear, concise answer.\n"
    "</think>\n\n"
    "The answer is **4**."
)

MOCK_RESPONSE = {
    "id": "chatcmpl-mock",
    "object": "chat.completion",
    "created": 1700000000,
    "model": "deepseek-r1:latest",
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": THINK_CONTENT,
            },
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 10, "completion_tokens": 50, "total_tokens": 60},
}


class _MockOllamaHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        request = json.loads(body) if body else {}

        if request.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            content = THINK_CONTENT
            for i in range(0, len(content), 20):
                chunk = {
                    "id": "chatcmpl-mock",
                    "object": "chat.completion.chunk",
                    "created": 1700000000,
                    "model": "deepseek-r1:latest",
                    "choices": [
                        {"index": 0, "delta": {"content": content[i : i + 20]}, "finish_reason": None}
                    ],
                }
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            final = {
                "id": "chatcmpl-mock",
                "object": "chat.completion.chunk",
                "created": 1700000000,
                "model": "deepseek-r1:latest",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            self.wfile.write(f"data: {json.dumps(final)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
        else:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(MOCK_RESPONSE).encode())

    def log_message(self, format, *args):
        pass


@pytest.fixture(scope="module")
def mock_ollama():
    """Start a mock ollama server on a random port."""
    server = HTTPServer(("127.0.0.1", 0), _MockOllamaHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}/v1"
    server.shutdown()


# ── Executor content extraction logic ─────────────────────────────────

def _get_executor_process_fn():
    """Extract the real content extraction logic from executor.py."""
    executor_path = (
        pathlib.Path(__file__).parent.parent / "src" / "subagents" / "executor.py"
    )
    source = executor_path.read_text()

    has_strip = "_strip_think_tags" in source

    if has_strip:
        match = re.search(
            r"(def _strip_think_tags\(content: str\) -> str:.*?)(?=\ndef )",
            source,
            re.DOTALL,
        )
        ns = {"re": re}
        exec(match.group(1), ns)
        strip_fn = ns["_strip_think_tags"]
    else:
        strip_fn = None

    def process(content):
        if isinstance(content, str):
            return strip_fn(content) if strip_fn else content
        elif isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, str):
                    text_parts.append(block)
                elif isinstance(block, dict) and "text" in block:
                    text_parts.append(block["text"])
            joined = "\n".join(text_parts) if text_parts else "No text content"
            return strip_fn(joined) if strip_fn else joined
        return str(content)

    return process, has_strip


# ── Tests ─────────────────────────────────────────────────────────────

class TestE2EThinkTagLeak:
    """End-to-end test proving <think> tag leakage through the real code path.

    Flow: mock ollama → LangChain ChatOpenAI → AIMessage.content → executor logic
    """

    def test_langchain_receives_think_tags_from_ollama(self, mock_ollama):
        """Step 1: Prove LangChain ChatOpenAI receives <think> tags in content."""
        llm = ChatOpenAI(
            model="deepseek-r1:latest",
            base_url=mock_ollama,
            api_key="not-needed",
            streaming=False,
        )
        response = llm.invoke([HumanMessage(content="What is 2+2?")])

        assert isinstance(response, AIMessage)
        assert isinstance(response.content, str)
        assert "<think>" in response.content, (
            f"Expected <think> in LangChain response content.\n"
            f"Got: {response.content[:200]}"
        )
        print("\n✅ LangChain ChatOpenAI received <think> tags in content")
        print(f"   content: {response.content[:100]}...")

    def test_executor_path_with_ollama_response(self, mock_ollama):
        """Step 2: Run ollama response through executor's content extraction."""
        llm = ChatOpenAI(
            model="deepseek-r1:latest",
            base_url=mock_ollama,
            api_key="not-needed",
            streaming=False,
        )
        response = llm.invoke([HumanMessage(content="What is 2+2?")])

        # Now run through executor's content extraction logic
        process_fn, has_strip = _get_executor_process_fn()
        result = process_fn(response.content)

        print(f"\n   Executor has _strip_think_tags: {has_strip}")
        print(f"   Input:  {response.content[:80]}...")
        print(f"   Output: {result[:80]}...")

        if has_strip:
            assert "<think>" not in result, f"REGRESSION: <think> still in result: {result[:200]}"
            assert "The answer is **4**." in result
            print("   ✅ PASS: <think> tags stripped by executor")
        else:
            assert "<think>" in result, f"Expected <think> in result: {result[:200]}"
            print("   ❌ BUG CONFIRMED: <think> tags leak through executor to user")

    def test_streaming_ollama_response(self, mock_ollama):
        """Step 3: Test streaming mode (how DeerFlow actually calls models)."""
        llm = ChatOpenAI(
            model="deepseek-r1:latest",
            base_url=mock_ollama,
            api_key="not-needed",
            streaming=True,
        )
        response = llm.invoke([HumanMessage(content="What is 2+2?")])

        process_fn, has_strip = _get_executor_process_fn()
        result = process_fn(response.content)

        print(f"\n   [streaming] Input:  {response.content[:80]}...")
        print(f"   [streaming] Output: {result[:80]}...")

        if has_strip:
            assert "<think>" not in result
            print("   ✅ PASS: Streaming <think> tags stripped")
        else:
            assert "<think>" in result
            print("   ❌ BUG CONFIRMED: Streaming <think> tags leak")

    def test_full_pipeline_simulation(self, mock_ollama):
        """Step 4: Full pipeline - ollama → LangChain → executor → user display."""
        # 1. Model call (simulating SubagentExecutor._run_agent)
        llm = ChatOpenAI(
            model="deepseek-r1:latest",
            base_url=mock_ollama,
            api_key="not-needed",
            streaming=False,
        )
        ai_message = llm.invoke([HumanMessage(content="What is 2+2?")])

        # 2. Content extraction (simulating SubagentExecutor.execute lines 290-304)
        process_fn, has_strip = _get_executor_process_fn()
        result = process_fn(ai_message.content)

        # 3. Frontend display (simulating extractContentFromMessage)
        # Frontend just does content.trim(), so same as result
        user_visible = result.strip()

        print("\n   === Full Pipeline ===")
        print(f"   Model output:   {ai_message.content[:80]}...")
        print(f"   After executor: {result[:80]}...")
        print(f"   User sees:      {user_visible[:80]}...")

        if has_strip:
            assert "<think>" not in user_visible
            assert "The answer is **4**." in user_visible
            print("   ✅ PASS: Full pipeline correctly strips <think> tags")
        else:
            assert "<think>" in user_visible
            print("   ❌ BUG CONFIRMED: <think> tags reach the user through full pipeline")
