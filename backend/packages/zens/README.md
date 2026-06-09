# Zens — Custom DeerFlow Extensions

Zens 是 DeerFlow 的扩展包，提供 Dify 多工作流路由、Data Analysis 等自定义扩展。

## 包结构

```
zens/
├── community/
│   └── dify/                    # Dify 多工作流集成
│       ├── dify_client.py      # Dify HTTP 客户端（blocking + streaming）
│       ├── router.py           # 统一调用入口（response_mode 路由 + LRU 对话缓存）
│       └── workflows/
│           ├── aml.py          # dify_aml_tool — 反洗钱工作流
│           ├── knowledge.py     # dify_knowledge_tool — 知识问答工作流
│           └── general.py      # dify_general_tool — 通用对话工作流
├── data_analysis/              # 数据分析扩展（开发中）
└── ...
```

## Dify 多工作流路由

### 核心设计

每个 Dify 工作流对应一个独立 `@tool`，通过 `router.py` 统一调用逻辑：

```
Agent                    router.py                    Dify API
  │                          │                            │
  ├─ dify_aml_tool ─────────►│                            │
  │                          ├── response_mode=blocking ──►│ /v1/chat-messages
  │                          │◄────────────────────────────┤
  │                          │                            │
  ├─ dify_knowledge_tool ────►│                            │
  │                          ├── response_mode=streaming ─►│ /v1/chat-messages
  │                          │◄── SSE chunks ──────────────┤
  │                          │                            │
  └─ dify_general_tool ─────►│                            │
                               └── response_mode=blocking ──►│ /v1/chat-messages
```

### 工作流工具

| Tool | 用途 | 触发场景 |
|------|------|----------|
| `dify_aml` | 反洗钱工作流（AML） | 可疑交易识别、交易监控、制裁名单筛查 |
| `dify_knowledge` | 知识问答工作流 | 知识库检索、百科查询、产品说明 |
| `dify_general` | 通用对话工作流 | 日常对话、闲聊、通用问题 |

### 核心组件

#### `DifyClient` (`dify_client.py`)

| 方法 | 用途 | 返回值 |
|------|------|--------|
| `chat(query, conversation_id, user, inputs=None, files=None)` | Blocking 模式调用 | `DifyResponse(answer, conversation_id, message_id)` |
| `chat_stream(query, conversation_id, user, inputs=None, files=None)` | Streaming 模式调用 | `tuple[list[str], str]` — (chunks, conversation_id) |
| `astream_chat(query, conversation_id, user, inputs=None, files=None)` | Async 流式（按 chunk 推送） | `AsyncIterator[DifyChunk]` |
| `await upload_file(file_path, user)` | 上传本地文件到 Dify `/v1/files/upload` | `DifyFileUpload` (含 `id` / `mime_type` / `name` / `size` 等) |

`inputs` 是 Dify `/v1/chat-messages` 请求体里的 `inputs` 字段，用于把工作流级变量（如 `mode`、`policy_classification`）注入 Dify workflow；不传则默认为 `{}`。
`files` 是 chat-messages 请求体里的 `files` 字段，元素是已经上传到 Dify 的文件引用 ``[{"type": ..., "transfer_method": "local_file", "upload_file_id": ...}]``；不传则默认为 `[]`。本地文件需要先调用 `upload_file` 拿到 `upload_file_id` 才能塞进这里。

#### `invoke_workflow` (`router.py`)

统一入口，按 `config.yaml` 中 `response_mode` 字段路由到 blocking 或 streaming：

```python
async def invoke_workflow(
    tool_name: str,       # "dify_aml" | "dify_knowledge" | "dify_general"
    query: str,           # 用户查询
    config: RunnableConfig = None,
    inputs: dict | None = None,  # 透传到 Dify 请求的 inputs 字段
    files: list[str] | None = None,  # 本地文件路径，会自动 upload 后塞进 files 字段
) -> str:                # AI 回答文本
```

特性：
- **对话缓存**：按 `(user_id, thread_id, workflow_name)` 维护 LRU 缓存（最大 1000 条）
- **Per-workflow 日志**：各工作流独立日志文件 `backend/logs/dify_{tool_name}.log`
- **线程安全**：锁保护共享状态

### config.yaml 配置示例

```yaml
tools:
  # === Dify 多工作流配置 ===

  - name: dify_aml
    use: zens.community.dify.workflows.aml:dify_aml_tool
    group: community
    api_key: $DIFY_AML_API_KEY
    base_url: http://localhost:8000
    response_mode: streaming    # blocking | streaming

  - name: dify_knowledge
    use: zens.community.dify.workflows.knowledge:dify_knowledge_tool
    group: community
    api_key: $DIFY_KNOWLEDGE_API_KEY
    base_url: http://localhost:8000
    response_mode: blocking

  - name: dify_general
    use: zens.community.dify.workflows.general:dify_general_tool
    group: community
    api_key: $DIFY_GENERAL_API_KEY
    base_url: http://localhost:8000
    response_mode: streaming
```

#### 字段说明

| 字段 | 必填 | 说明 |
|------|------|------|
| `name` | ✅ | 工具标识，用于 `config.yaml` 内部查找 |
| `use` | ✅ | 模块路径格式 `package:export`，LangChain `@tool` 加载器解析 |
| `group` | ✅ | 工具分组，`community` 为社区扩展组 |
| `api_key` | ✅ | Dify API Key，支持 `$ENV_VAR` 环境变量引用 |
| `base_url` | ✅ | Dify 实例地址，默认为 `http://localhost:8000` |
| `response_mode` | ❌ | 默认为 `blocking`；`streaming` 启用 SSE 流式响应 |

### 环境变量

在 `.env` 或系统环境中配置 Dify API Keys：

```bash
DIFY_AML_API_KEY=app-xxxxxxxxxxxx
DIFY_KNOWLEDGE_API_KEY=app-yyyyyyyyyyyy
DIFY_GENERAL_API_KEY=app-zzzzzzzzzzzz
```

### 日志

运行时日志目录：`backend/logs/`

```
backend/logs/
├── dify.log              # DifyClient 所有请求日志
├── dify_aml.log         # dify_aml 工作流专用日志
├── dify_knowledge.log    # dify_knowledge 工作流专用日志
└── dify_general.log      # dify_general 工作流专用日志
```

### 测试

```bash
cd backend
PYTHONPATH=. uv run pytest packages/zens/tests/test_dify_streaming.py -v        # 流式解析测试
PYTHONPATH=. uv run pytest packages/zens/tests/test_dify_workflow_tools.py -v   # 工作流工具加载测试
```

## 开发

### 添加新工作流

1. 在 `zens/community/dify/workflows/` 下创建新文件（如 `risk.py`）
2. 实现 `@tool("dify_risk", parse_docstring=True)` 装饰的函数，调用 `invoke_workflow("dify_risk", query, config)`
3. 在 `workflows/__init__.py` 和主 `__init__.py` 中导出
4. 在 `config.yaml` 中添加配置（配置 `response_mode`）