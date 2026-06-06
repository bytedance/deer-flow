# Dify Tool 真正流式输出 — Implementation Plan

## Task 1 — `DifyClient` 新增 `astream_chat` + `DifyChunk`

**文件**: `backend/packages/zens/zens/community/dify/dify_client.py`

1. 新增 `DifyChunk` pydantic 模型(与现有 `DifyResponse` 风格一致)
2. 新增 `DifyClient.astream_chat(query, conversation_id, user, timeout=60.0) -> AsyncIterator[DifyChunk]`
   - 用 `httpx.AsyncClient(timeout=timeout) as ac` + `ac.stream("POST", url, ...)` 异步上下文
   - 进入 `ac.stream` 上下文后先 `if not response.is_success` → `await response.aread()` → 抛 `DifyAPIError`
   - 解析 `event: message` / `data: {...}` 与现有 `chat_stream` 同样的规则
   - 每个 `answer` 非空就 `yield DifyChunk(answer=..., conversation_id=..., message_id=...)`
3. 保留现有 `chat_stream` 同步方法不动

**验证**: `PYTHONPATH=packages/zens:packages/harness rtk python -c "import asyncio; from zens.community.dify.dify_client import DifyClient; print(asyncio.iscoroutinefunction(DifyClient.astream_chat))"` 输出 `True`

## Task 2 — `router.invoke_workflow` 改 async + 推送 `dify_*` 事件

**文件**: `backend/packages/zens/zens/community/dify/router.py`

1. 顶部 import 增加 `from collections.abc import AsyncIterator`(只在 client 用了) + `from langgraph.config import get_stream_writer`
2. `def invoke_workflow(...)` 改成 `async def invoke_workflow(...)`
3. 流式分支:
   ```python
   if tool_cfg.response_mode == "streaming":
       writer = get_stream_writer()
       writer({"type": "dify_started", "tool": tool_name, "query_len": len(query)})
       full: list[str] = []
       last_conv = ""
       try:
           async for chunk in client.astream_chat(
               query=query, conversation_id=conversation_id, user=user,
           ):
               full.append(chunk.answer)
               if chunk.conversation_id:
                   last_conv = chunk.conversation_id
               writer({"type": "dify_chunk", "tool": tool_name,
                       "delta": chunk.answer, "index": len(full) - 1})
       except DifyAPIError as e:
           writer({"type": "dify_failed", "tool": tool_name,
                   "status_code": e.status_code, "message": e.message})
           raise
       if last_conv:
           _cache_conversation(cache_key, last_conv)
       full_answer = "".join(full)
       writer({"type": "dify_completed", "tool": tool_name,
               "total_len": len(full_answer), "conversation_id": last_conv})
       return full_answer
   ```
4. 阻塞分支保持原样(直接在 async 函数里调同步 `client.chat(...)`,本期范围不动)

**验证**: `rtk python -c "import inspect; from zens.community.dify.router import invoke_workflow; print(inspect.iscoroutinefunction(invoke_workflow))"` 输出 `True`

## Task 3 — 测试

**文件**:
- `backend/packages/zens/tests/test_dify_streaming.py` (扩展)
- `backend/packages/zens/tests/test_router_streaming.py` (新增)

### test_dify_streaming.py 新增

- `test_astream_chat_yields_dify_chunks_per_message_event` — 2 个 message 事件 → 2 个 DifyChunk
- `test_astream_chat_filters_ping_events` — 混 ping → 只 message 计入
- `test_astream_chat_http_error_raises_dify_api_error` — 401 → DifyAPIError(401, ...)
- `test_astream_chat_timeout_raises_dify_api_error` — TimeoutException → DifyAPIError(0, "Request to Dify timed out")

用 `FakeAsyncClient` + `FakeAsyncStreamResponse` 模拟 `httpx.AsyncClient.stream()`,patch 掉 `httpx.AsyncClient`。

### test_router_streaming.py 新增

- `test_invoke_workflow_streaming_emits_dify_started_chunk_completed` — 流式路径,3 个 chunk,验证事件顺序和 payload
- `test_invoke_workflow_streaming_emits_dify_failed_and_reraises` — `astream_chat` 抛 DifyAPIError → 推 dify_failed + 重新抛
- `test_invoke_workflow_streaming_returns_joined_answer` — 工具返回值是 `"".join(chunks)`,LLM 拿到完整串
- `test_invoke_workflow_blocking_emits_no_events` — 阻塞路径不推任何事件,只返回 answer

## Task 4 — 跑测试

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow/backend
PYTHONPATH=packages/zens:packages/harness rtk python -m pytest \
  packages/zens/tests/test_dify_streaming.py \
  packages/zens/tests/test_router_streaming.py \
  packages/zens/tests/test_dify_workflow_tools.py -v
```

预期:全部 pass,旧的 `test_chat_stream_*` 4 个继续绿(零回归)。

## Task 5 — 验证整体

- `make test` 或 `cd backend && make test` 不报新失败
- `ruff check` 不报 lint 错误
