# Dify Chat Tool — Design

## Status

Draft → Approved

## Background

User wants to integrate Dify chatflow (`app-ZzvO2ic3KveYOeQcI4xYT8Qq`) as a tool in DeerFlow. Dify is a chatflow-type app that supports multi-turn conversations via `conversation_id`. The integration should act as a callable tool the agent can invoke to delegate a user query to Dify and get a text response back.

## Approach

**Tool（工具）** — `dify_chat` tool that agent calls directly, not a Skill.

Multi-turn support via per-thread `conversation_id` mapping so context is preserved within a DeerFlow thread.

---

## Architecture

```
backend/packages/zens/zens/community/dify/
├── __init__.py        # Package init, exports dify_chat_tool
├── dify_client.py    # DifyClient: HTTP client + stateful conversation mapping
└── tools.py           # @tool decorator + tool function
```

Follows the same pattern as `deerflow.community.tavily` but lives under the `zens` Python package (a local-first extension to deerflow-harness).

---

## Files

### `dify_client.py`

```python
class DifyClient:
    def __init__(
        self,
        api_key: str,
        app_id: str,
        base_url: str = "http://localhost:8000",
    ): ...

    def chat(
        self,
        query: str,
        conversation_id: str,
        user: str,
    ) -> DifyResponse: ...
```

`DifyResponse`:
```python
class DifyResponse(BaseModel):
    answer: str
    conversation_id: str
    message_id: str
```

Implementation:
- POST `$base_url/v1/chat-messages`
- Headers: `Authorization: Bearer {api_key}`, `Content-Type: application/json`
- Body: `{ inputs: {}, query, response_mode: "blocking", conversation_id, user, files: [] }`
- On 200: parse `answer` + `conversation_id` from JSON response
- On error: raise `DifyAPIError`

Supports only `response_mode: blocking` (not streaming). Streaming would require SSE handling which is complex for a first implementation.

### `tools.py`

```python
from deerflow.community.dify.dify_client import DifyClient, DifyResponse

_dify_clients: dict[str, DifyClient] = {}  # key = user_id
_conversation_ids: dict[str, str] = {}      # key = f"{user_id}:{thread_id}", value = conversation_id
_tool_config: ToolConfig | None = None

def _get_dify_client() -> DifyClient:
    config = get_app_config().get_tool_config("dify_chat")
    api_key = config.model_extra.get("api_key") if config else None
    app_id = config.model_extra.get("app_id") or "app-ZzvO2ic3KveYOeQcI4xYT8Qq"
    base_url = config.model_extra.get("base_url") or "http://localhost:8000"
    user_id = get_effective_user_id()
    if user_id not in _dify_clients:
        _dify_clients[user_id] = DifyClient(api_key=api_key, app_id=app_id, base_url=base_url)
    return _dify_clients[user_id]

@tool("dify_chat", parse_docstring=True)
def dify_chat_tool(query: str) -> str:
    """Ask a Dify chatflow agent.

    Args:
        query: The question to ask the Dify agent.
    """
    user_id = get_effective_user_id()
    thread_id = get_current_thread_id()   # from deerflow.runtime.user_context
    cache_key = f"{user_id}:{thread_id}"

    conversation_id = _conversation_ids.get(cache_key, "")
    user = f"deerflow_{user_id}"

    client = _get_dify_client()
    response = client.chat(query=query, conversation_id=conversation_id, user=user)

    # Cache conversation_id for next call in same thread
    if response.conversation_id:
        _conversation_ids[cache_key] = response.conversation_id

    return response.answer
```

**Key decisions:**
- `thread_id` from `deerflow.runtime.user_context` via `get_current_thread_id()`
- Per-(user, thread) mapping for `conversation_id` so different threads maintain independent Dify sessions
- Uses `get_app_config().get_tool_config("dify_chat")` for config (same pattern as Tavily)
- Falls back to hardcoded `app_id` if not in config

### `__init__.py`

```python
from deerflow.community.dify.tools import dify_chat_tool

__all__ = ["dify_chat_tool"]
```

---

## Configuration

```yaml
tools:
  - name: dify_chat
    group: community
    use: zens.community.dify.tools:dify_chat_tool
```

Config fields via `model_extra`:
- `api_key` (required): Dify API key
- `app_id` (optional): defaults to `app-ZzvO2ic3KveYOeQcI4xYT8Qq`
- `base_url` (optional): defaults to `http://localhost:8000`

User must set `DIFY_API_KEY` env var or put it directly in `config.yaml`.

---

## Testing

- `tests/test_dify_tool.py`: unit tests for `DifyClient` (mocked responses) and `dify_chat_tool` (mocked client)
- Verify conversation_id caching across multiple calls in same thread
- Verify different threads get independent conversation_ids

---

## Out of Scope

- Streaming response mode (blocking only)
- File/image attachments
- Input variable substitution (`inputs` field)
- Dify MCP integration

---

## Spec Self-Review

- Placeholder scan: no TBD/TODO
- Internal consistency: client handles error, tool uses correct thread key
- Scope: single tool, one file for client, one for tool
- Ambiguity: `get_current_thread_id()` - verify it exists in `deerflow.runtime.user_context`