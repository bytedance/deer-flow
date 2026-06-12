# Dify 多工作流路由 Tool 设计

## 背景

DeerFlow 目前通过单个 `dify_chat_tool` 调用一个 Dify 工作流。用户需要根据不同意图（反洗钱 AML / 知识问答 / 通用）路由到不同的 Dify 工作流。

## 目标

支持多个 Dify 工作流作为独立 Tool，Lead Agent 根据用户输入自主选择调用哪个 Tool。支持 **blocking** 和 **streaming** 两种 response_mode。

## 设计

### 架构

```
用户输入
  → Lead Agent（多个 dify_* tool schema 一次性注入）
    → LLM function calling 选择对应 tool
      → dify_aml_tool / dify_knowledge_tool / dify_general_tool
        → DifyClient(api_key, base_url).chat(response_mode=blocking|streaming)
          → Dify 工作流返回结果（text 或 stream）
```

### 目录结构（仅 packages/zens）

```
backend/packages/zens/zens/community/dify/
  ├── __init__.py
  ├── client.py          # DifyClient（支持 blocking + streaming）
  ├── router.py         # 新增：统一 client factory，按 tool_name 读取配置
  ├── workflows/
  │   ├── __init__.py
  │   ├── aml.py        # 新增：dify_aml_tool 定义
  │   ├── knowledge.py  # 新增：dify_knowledge_tool 定义
  │   └── general.py    # 新增：dify_general_tool 定义
  └── tools.py          # 废弃：原有 dify_chat_tool（移除）
```

### 每个 Workflow Tool

独立函数，独立 `@tool`，独立 docstring 作为 LLM 路由信号：

```python
# workflows/aml.py
@tool("dify_aml", parse_docstring=True)
def dify_aml_tool(query: str, config: Annotated[RunnableConfig, InjectedToolArg] = None) -> str:
    """反洗钱工作流（AML）。

    当用户问到以下场景时调用：
    - 可疑交易识别 / 交易监控 / 洗钱风险
    - 金融机构合规 / 监管要求（反洗钱）
    - 客户尽职调查（CDD）/ 交易筛选

    Args:
        query: 用户的 AML 相关问题。
    """
    return _invoke_workflow("dify_aml", query, config)
```

### 统一 Router（router.py）

每个 workflow tool 的路由逻辑统一走 `router.py`：

```python
def _invoke_workflow(tool_name: str, query: str, config) -> str:
    # 1. 读取 tool 配置（api_key, base_url, response_mode）
    tool_cfg = _get_tool_config(tool_name)
    client = DifyClient(api_key=tool_cfg.api_key, base_url=tool_cfg.base_url)

    # 2. 从 config 提取 thread_id/user_id，维护各自的 conversation_id
    user_id = get_effective_user_id()
    thread_id = _get_thread_id(config)
    cache_key = f"{user_id}:{thread_id}:{tool_name}"
    conversation_id = _get_cached_conversation(cache_key)
    user = f"deerflow_{user_id}"

    # 3. 读取 response_mode，调用 DifyClient.chat()
    response_mode = tool_cfg.response_mode  # "blocking" | "streaming"
    if response_mode == "streaming":
        return _streaming_invoke(client, query, conversation_id, user, cache_key)
    else:
        response = client.chat(query=query, conversation_id=conversation_id, user=user)
        if response.conversation_id:
            _cache_conversation(cache_key, response.conversation_id)
        return response.answer


def _streaming_invoke(client, query, conversation_id, user, cache_key) -> str:
    """Streaming 模式：实时 yield chunks，拼装完整 answer 后缓存 conversation_id。"""
    chunks = []
    conversation_id_result = [conversation_id]

    for chunk in client.chat_stream(query=query, conversation_id=conversation_id, user=user):
        chunks.append(chunk)
        yield chunk  # 让 caller 实时消费

    full_answer = "".join(chunks)
    # 从最后一个 chunk 提取 conversation_id 并缓存
    # （streaming 响应末尾包含 conversation_id）
    if conversation_id_result[0]:
        _cache_conversation(cache_key, conversation_id_result[0])
    return full_answer
```

### 对话缓存 Key 变更

原：`{user_id}:{thread_id}`
新：`{user_id}:{thread_id}:{workflow_name}`

各工作流独立维护对话历史，互不干扰。

### config.yaml 配置示例

```yaml
tools:
  - name: dify_aml
    use: zens.community.dify.workflows.aml:dify_aml_tool
    group: community
    api_key: $DIFY_AML_API_KEY
    base_url: http://localhost:8000
    response_mode: blocking

  - name: dify_knowledge
    use: zens.community.dify.workflows.knowledge:dify_knowledge_tool
    group: community
    api_key: $DIFY_KNOWLEDGE_API_KEY
    base_url: http://localhost:8000
    response_mode: streaming

  - name: dify_general
    use: zens.community.dify.workflows.general:dify_general_tool
    group: community
    api_key: $DIFY_GENERAL_API_KEY
    base_url: http://localhost:8000
    response_mode: blocking
```

### 日志设计

每个 workflow 独立的 logger name，写入 `logs/dify_{workflow}.log`：

```python
# router.py
_workflow_loggers: dict[str, logging.Logger] = {}


def _get_workflow_logger(tool_name: str) -> logging.Logger:
    if tool_name not in _workflow_loggers:
        logger = logging.getLogger(f"zens.community.dify.{tool_name}")
        logger.setLevel(logging.DEBUG)
        _logs_dir = Path(__file__).resolve().parent.parent.parent.parent / "logs"
        _logs_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(_logs_dir / f"dify_{tool_name}.log", mode="a", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        logger.addHandler(handler)
        _workflow_loggers[tool_name] = logger
    return _workflow_loggers[tool_name]
```

## 行为变更

| 变更点 | 说明 |
|---|---|
| 移除 | 原 `dify_chat_tool`（单个统一入口） |
| 新增 | `dify_aml_tool` / `dify_knowledge_tool` / `dify_general_tool` |
| 新增 | `DifyClient.chat_stream()` 支持 streaming 模式 |
| 对话缓存 | 每个 (user_id, thread_id, workflow_name) 独立缓存 |
| 日志 | 各 workflow 独立 logger，写入 `logs/dify_{workflow}.log` |
| 配置 | 新增 `response_mode` 字段（blocking / streaming） |

## DifyClient 变更（client.py）

```python
class DifyClient:
    def chat(self, query, conversation_id, user, timeout=60.0,
             response_mode: str = "blocking") -> DifyResponse:
        # 现有实现，response_mode="blocking" 时直接 POST
        ...

    def chat_stream(self, query, conversation_id, user, timeout=60.0,
                    response_mode: str = "streaming"):
        """Streaming 模式：YEILD text chunks，保留 conversation_id。"""
        url = f"{self.base_url}/v1/chat-messages"
        # POST 时 response_mode="streaming"，然后迭代 response.lines()
        ...
```

Dify streaming API 返回 SSE lines，需要解析 `conversation_id` 和 `answer` 从 events 中。

## 错误处理

各 workflow tool 的异常统一捕获：
- 配置缺失 → `DifyAPIError(0, "xxx api_key not configured")`
- Dify 超时 → `DifyAPIError(0, "Request to Dify timed out")`
- Dify 返回非 2xx → `DifyAPIError(status_code, message)`

## 测试

- `test_dify_workflow_tools.py`：验证各 tool 可独立加载、invoke、缓存独立
- `test_dify_client_request.py`：验证各 tool 调用时使用正确的 api_key/base_url
- `test_dify_streaming.py`：验证 streaming 模式 chunk 拼装正确
- 废弃：`tests/test_dify_tool.py`（移除对旧 `dify_chat_tool` 的引用）