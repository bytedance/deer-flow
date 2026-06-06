# Dify Tool 真正流式输出 — Design

## 目标

Dify 工作流工具 (`dify_*`) 当前是"假流式": `DifyClient.chat_stream()` 把 Dify 全部 SSE chunk 收完
才返回 `tuple[list[str], str]`,`router.invoke_workflow` 再 `"".join(chunks)` 拼成单字符串。
前端在工具完成前**完全看不到**任何输出,体感等同于阻塞调用。

改成真流式: 工具运行中每收到一个 Dify chunk,立即推 `dify_chunk` 事件给前端。

## 不在范围内

- 不动 `chat_stream` 同步接口(保留供其它调用方,例如一次性脚本)
- 不动所有 7 个 workflow 工具 (`aml/document_review/general/image_recognition/knowledge/policy_qa/writing`) 的签名
- 不动阻塞 (`response_mode == "blocking"`) 分支
- 不动 `return_direct=True`,继续短路 lead agent

## 分层与职责

| 层 | 文件 | 当前 | 改动 |
|---|---|---|---|
| HTTP 传输 | `dify_client.py` | 同步 `chat_stream() -> (chunks, conv_id)` | 新增 `astream_chat() -> AsyncIterator[DifyChunk]`,用 `httpx.AsyncClient.stream()` + `aiter_lines()` |
| LangChain 工具 | `router.py::invoke_workflow` | `def`,阻塞模式无流,流式模式 `"".join` | 改 `async def`,流式分支用 `langgraph.config.get_stream_writer()` 逐 chunk 推 `dify_*` 事件 |

**DifyClient 仍零 LangGraph 依赖**。事件归属工具层。

## 接口设计

### DifyClient

```python
class DifyChunk(BaseModel):
    answer: str
    conversation_id: str
    message_id: str = ""

class DifyClient:
    # 保留旧接口,行为不变
    def chat_stream(self, query, conversation_id, user, timeout=60.0) -> tuple[list[str], str]: ...

    # 新接口
    async def astream_chat(
        self, query, conversation_id, user, timeout=60.0,
    ) -> AsyncIterator[DifyChunk]:
        # async with httpx.AsyncClient(timeout=timeout) as ac:
        #   async with ac.stream("POST", url, json=payload, headers=headers) as response:
        #     if not response.is_success: raise DifyAPIError(...)
        #     current_event = None
        #     async for line in response.aiter_lines():
        #       if line.startswith("event: "): current_event = line[7:].strip(); continue
        #       if not line.startswith("data: ") or current_event != "message": continue
        #       data = json.loads(line[6:].strip())
        #       answer = data.get("answer", "")
        #       if not answer: continue
        #       yield DifyChunk(answer=answer, conversation_id=data.get("conversation_id", ""), ...)
```

### invoke_workflow 事件协议

| 事件 | 何时推 | payload |
|---|---|---|
| `dify_started` | 流式分支入口 | `tool`, `query_len` |
| `dify_chunk` | 每个 Dify chunk | `tool`, `delta`, `index` |
| `dify_completed` | 全部 chunk 收完 | `tool`, `total_len`, `conversation_id` |
| `dify_failed` | 抛 `DifyAPIError` | `tool`, `status_code`, `message` |

事件名沿用 `task_*` 命名空间风格(参考 `task_tool.py`)。
阻塞分支不推任何事件。

## 失败模式

- HTTP 错误 → 同步路径已正确抛 `DifyAPIError`,异步路径在 `ac.stream(...)` `__aenter__` 后立刻检查
- 超时 → `httpx.TimeoutException` 在 `ac.stream(...)` 入口抛,包成 `DifyAPIError(0, "Request to Dify timed out")`
- Dify 业务错误(非 message event)→ 静默忽略,与 `chat_stream` 一致

## 与 LangGraph / frontend 的对接

- `get_stream_writer()` 写入的事件对应 LangGraph `stream_mode="custom"`
- `DeerFlowClient.stream` 已订阅 `["values", "messages", "custom"]`,无需改前端或网关
- 事件名 `dify_*` 是新命名空间;前端 `MessageList` 可加一个分发器把 `dify_chunk.delta` 拼到当前 assistant message
  (本期不在本 PR 范围,只确保事件被推出去,前端读取是后续工作)

## 兼容性

- 旧 `chat_stream` 同步接口保留,所有现有 `test_chat_stream_*` 测试继续通过
- 7 个 workflow 工具的 `coroutine` 字段自动切换到新的 async `invoke_workflow`,LangChain 工具层无感
