# Dify Chat Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `dify_chat` tool that delegates user queries to a Dify chatflow app, with multi-turn conversation support per DeerFlow thread.

**Architecture:** `zens.community.dify` package under the `zens` Python package (which already declares `deerflow-harness` as a workspace dependency). Two files: `dify_client.py` (HTTP client + response/error models) and `tools.py` (`@tool` function). `conversation_id` stored in a module-level dict keyed by `f"{user_id}:{thread_id}"`, resolved from `RunnableConfig` via `InjectedToolArg`. The tool is registered in `config.yaml` via `use: zens.community.dify.tools:dify_chat_tool`.

**Tech Stack:** `httpx`, `pydantic`, LangChain `@tool`, `langchain_core.runnables.RunnableConfig`

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `backend/packages/zens/zens/community/dify/__init__.py` | Create | Package init, exports `dify_chat_tool` |
| `backend/packages/zens/zens/community/dify/dify_client.py` | Create | `DifyClient`, `DifyResponse`, `DifyAPIError` |
| `backend/packages/zens/zens/community/dify/tools.py` | Create | `@tool("dify_chat")`, conversation mapping |
| `config.example.yaml` | Modify | Add `dify_chat` tool entry |
| `tests/test_dify_tool.py` | Create | Unit tests for client + tool |

---

## Task 1: Write `dify_client.py`

**Files:**
- Create: `backend/packages/zens/zens/community/dify/dify_client.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dify_tool.py
import pytest
from zens.community.dify.dify_client import DifyAPIError, DifyClient, DifyResponse

def test_dify_response_model():
    r = DifyResponse(answer="hello", conversation_id="conv123", message_id="msg456")
    assert r.answer == "hello"
    assert r.conversation_id == "conv123"
    assert r.message_id == "msg456"

def test_dify_api_error():
    e = DifyAPIError(401, "invalid api key")
    assert e.status_code == 401
    assert "401" in str(e)
    assert "invalid api key" in str(e)

def test_dify_client_chat_request(monkeypatch):
    client = DifyClient(api_key="test-key", app_id="app-123", base_url="http://localhost:8000")
    recorded_request = {}

    class FakeResponse:
        status_code = 200
        is_success = True
        def json(self):
            return {"answer": "hi", "conversation_id": "conv-new", "message_id": "msg-new"}

    class FakeHttpx:
        def post(self, url, **kwargs):
            recorded_request["url"] = url
            recorded_request["headers"] = kwargs.get("headers")
            recorded_request["json"] = kwargs.get("json")
            return FakeResponse()

    import zens.community.dify.dify_client as mod
    monkeypatch.setattr(mod, "httpx", FakeHttpx())
    response = client.chat(query="hello", conversation_id="", user="u1")
    assert response.answer == "hi"
    assert recorded_request["json"]["query"] == "hello"
    assert recorded_request["json"]["response_mode"] == "blocking"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/test_dify_tool.py::test_dify_response_model tests/test_dify_tool.py::test_dify_api_error -v 2>&1 | head -30
```
Expected: `FAILED` (module not found)

- [ ] **Step 3: Write minimal implementation**

```python
"""Dify HTTP client for chatflow apps."""

import logging

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class DifyAPIError(Exception):
    """Raised when Dify API returns a non-2xx response."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"Dify API error {status_code}: {message}")


class DifyResponse(BaseModel):
    answer: str
    conversation_id: str
    message_id: str


class DifyClient:
    def __init__(
        self,
        api_key: str,
        app_id: str,
        base_url: str = "http://localhost:8000",
    ):
        self.api_key = api_key
        self.app_id = app_id
        self.base_url = base_url.rstrip("/")

    def chat(
        self,
        query: str,
        conversation_id: str,
        user: str,
        timeout: float = 60.0,
    ) -> DifyResponse:
        """Send a chat message to the Dify chatflow."""
        url = f"{self.base_url}/v1/chat-messages"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "inputs": {},
            "query": query,
            "response_mode": "blocking",
            "conversation_id": conversation_id,
            "user": user,
            "files": [],
        }

        try:
            response = httpx.post(url, json=payload, headers=headers, timeout=timeout)
        except httpx.TimeoutException:
            raise DifyAPIError(0, "Request to Dify timed out")

        if not response.is_success:
            try:
                error_body = response.json()
                message = error_body.get("message", response.text)
            except Exception:
                message = response.text or "Unknown error"
            raise DifyAPIError(response.status_code, message)

        data = response.json()
        return DifyResponse(
            answer=data.get("answer", ""),
            conversation_id=data.get("conversation_id", ""),
            message_id=data.get("message_id", ""),
        )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/test_dify_tool.py::test_dify_response_model tests/test_dify_tool.py::test_dify_api_error -v
```
Expected: `PASS`

- [ ] **Step 5: Run full client tests**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/test_dify_tool.py -v
```
Expected: All tests in file pass

- [ ] **Step 6: Commit**

```bash
rtk git add backend/packages/zens/zens/community/dify/dify_client.py tests/test_dify_tool.py
rtk git commit -m "feat(dify): add DifyClient and DifyResponse model"
```

---

## Task 2: Write `tools.py` and `__init__.py`

**Files:**
- Create: `backend/packages/zens/zens/community/dify/tools.py`
- Create: `backend/packages/zens/zens/community/dify/__init__.py`

- [ ] **Step 1: Write the failing test**

```python
# Add to tests/test_dify_tool.py

def test_dify_chat_tool_no_api_key(monkeypatch):
    import zens.community.dify.tools as tools_mod

    monkeypatch.setattr(tools_mod, "_get_dify_client", lambda: (_ for _ in ()).throw(DifyAPIError(0, "no key")))

    from zens.community.dify.tools import dify_chat_tool
    try:
        dify_chat_tool.invoke({"query": "hello"})
        assert False, "should have raised"
    except DifyAPIError as e:
        assert "no key" in str(e)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/test_dify_tool.py::test_dify_chat_tool_no_api_key -v 2>&1 | head -20
```
Expected: `FAILED`

- [ ] **Step 3: Write `__init__.py`**

```python
"""Dify community tool for DeerFlow zens extension."""

from zens.community.dify.tools import dify_chat_tool

__all__ = ["dify_chat_tool"]
```

- [ ] **Step 4: Write `tools.py`**

```python
"""Dify chat tool for DeerFlow agent."""

import logging
from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg
from langchain.tools import tool

from deerflow.config import get_app_config
from deerflow.runtime.user_context import get_effective_user_id
from zens.community.dify.dify_client import DifyAPIError, DifyClient

logger = logging.getLogger(__name__)

# Per-(user_id, thread_id) → Dify conversation_id
_conversation_ids: dict[str, str] = {}


def _get_dify_client() -> DifyClient:
    config = get_app_config().get_tool_config("dify_chat")
    api_key: str | None = None
    if config is not None and "api_key" in config.model_extra:
        api_key = config.model_extra.get("api_key")

    app_id = (
        config.model_extra.get("app_id") if config else None
    ) or "app-ZzvO2ic3KveYOeQcI4xYT8Qq"
    base_url = (
        config.model_extra.get("base_url") if config else None
    ) or "http://localhost:8000"

    if not api_key:
        raise DifyAPIError(0, "Dify api_key is not configured. Set 'api_key' in the dify_chat tool config or DIFY_API_KEY env var.")

    return DifyClient(api_key=api_key, app_id=app_id, base_url=base_url)


def _get_thread_id(config: RunnableConfig | None) -> str:
    """Extract thread_id from RunnableConfig, or return 'default'."""
    if config is None:
        return "default"
    configurable = config.get("configurable") or {}
    thread_id = configurable.get("thread_id")
    if thread_id is None:
        return "default"
    return str(thread_id)


@tool("dify_chat", parse_docstring=True)
def dify_chat_tool(
    query: str,
    config: Annotated[RunnableConfig, InjectedToolArg] = None,
) -> str:
    """Ask a Dify chatflow agent.

    Delegates the user's question to a Dify chatflow application and returns
    the agent's text response. Maintains conversation context within the same
    DeerFlow thread.

    Args:
        query: The question to ask the Dify agent.
    """
    user_id = get_effective_user_id()
    thread_id = _get_thread_id(config)
    cache_key = f"{user_id}:{thread_id}"

    conversation_id = _conversation_ids.get(cache_key, "")
    user = f"deerflow_{user_id}"

    client = _get_dify_client()

    try:
        response = client.chat(query=query, conversation_id=conversation_id, user=user)
    except DifyAPIError:
        raise
    except Exception as exc:
        raise DifyAPIError(0, f"Unexpected error: {exc}") from exc

    # Cache conversation_id for next call in same thread
    if response.conversation_id:
        _conversation_ids[cache_key] = response.conversation_id

    return response.answer
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/test_dify_tool.py -v
```

- [ ] **Step 6: Commit**

```bash
rtk git add backend/packages/zens/zens/community/dify/
rtk git commit -m "feat(dify): add dify_chat_tool with multi-turn support"
```

---

## Task 3: Add config entry

**Files:**
- Modify: `config.example.yaml`

- [ ] **Step 1: Find the right location in config.example.yaml**

```bash
grep -n "^tools:" /Users/raidery/bench/harness/raidery/deer-flow/config.example.yaml
```
Expected output: line number where `tools:` section begins

- [ ] **Step 2: Add `dify_chat` entry after `image_search_tool` entry (around line 463)**

Insert after the `image_search_tool` block:
```yaml
  - name: dify_chat
    group: community
    use: zens.community.dify.tools:dify_chat_tool
    # api_key: $DIFY_API_KEY  # Required: your Dify API key
    # app_id: app-ZzvO2ic3KveYOeQcI4xYT8Qq  # Optional: defaults to this app
    # base_url: http://localhost:8000  # Optional: defaults to localhost:8000
```

- [ ] **Step 3: Commit**

```bash
rtk git add config.example.yaml
rtk git commit -m "feat(config): add dify_chat tool to config.example.yaml"
```

---

## Task 4: Add end-to-end conversation test

**Files:**
- Modify: `tests/test_dify_tool.py`

- [ ] **Step 1: Write multi-turn conversation test**

```python
def test_conversation_id_caching(monkeypatch):
    """Verify conversation_id is cached per (user, thread) and reused."""
    call_count = [0]

    class FakeDifyResponse:
        def __init__(self, conv_id):
            self.conversation_id = conv_id
            self.answer = f"answer for {conv_id}"
            self.message_id = f"msg-{conv_id}"

    class FakeDifyClient:
        def __init__(self, **kwargs):
            pass
        def chat(self, query, conversation_id, user):
            call_count[0] += 1
            if call_count[0] == 1:
                return FakeDifyResponse("conv-1")
            return FakeDifyResponse(f"conv-reuse-{conversation_id}")

    import zens.community.dify.tools as tools_mod
    monkeypatch.setattr(tools_mod, "_get_dify_client", lambda: FakeDifyClient())
    monkeypatch.setattr(tools_mod, "_conversation_ids", {})

    # Reset conversation state
    tools_mod._conversation_ids.clear()

    class FakeRunnableConfig(dict):
        def get(self, key, default=None):
            if key == "configurable":
                return {"thread_id": "thread-abc"}
            return super().get(key, default)

    cfg = FakeRunnableConfig(configurable={"thread_id": "thread-abc"})

    result1 = tools_mod.dify_chat_tool.invoke({"query": "hello", "config": cfg})
    assert "answer for conv-1" in result1
    assert tools_mod._conversation_ids.get("default:thread-abc") == "conv-1"

    result2 = tools_mod.dify_chat_tool.invoke({"query": "follow up", "config": cfg})
    assert "conv-reuse-conv-1" in result2
```

- [ ] **Step 2: Run test**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/test_dify_tool.py::test_conversation_id_caching -v
```

- [ ] **Step 3: Commit**

```bash
rtk git add tests/test_dify_tool.py
rtk git commit -m "test(dify): add multi-turn conversation_id caching test"
```

---

## Task 5: Final verification

- [ ] **Step 1: Run full backend test suite**

```bash
cd backend && make test 2>&1 | tail -30
```

- [ ] **Step 2: Verify tool can be imported**

```bash
cd backend && PYTHONPATH=. uv run python -c "from zens.community.dify import dify_chat_tool; print('OK')"
```

---

## Self-Review Checklist

1. **Spec coverage:** All requirements from the design doc are implemented in tasks 1-4.
2. **Placeholder scan:** No TBD/TODO in plan. All code blocks are complete.
3. **Type consistency:** `DifyResponse.answer`, `DifyResponse.conversation_id`, `DifyClient.chat()` signature — all consistent across tasks.
4. **`httpx` dependency:** Already in `zens/pyproject.toml` (`"httpx>=0.27.0"`), no change needed.
5. **`deerflow-harness` dependency:** Already in `zens/pyproject.toml` as workspace dep, `_get_dify_client()` can call `deerflow.config.get_app_config()` and `deerflow.runtime.user_context.get_effective_user_id()`.
6. **Import direction:** `zens.community.dify` imports from `deerflow.*` — this is allowed because `zens` is in the app layer and harness never imports app.