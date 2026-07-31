# RAG 知识库 MCP Server 设计文档

**日期：** 2026-07-16
**状态：** 已确认，待实现
**来源文档：** `组织化数字分身平台选型与 PoC 方案.md`

---

## 1. 目标

构建一个独立的 RAG 知识库 MCP Server（`kb-mcp`），通过 MCP 协议接入 DeerFlow Agent 运行时，使 Agent 能够在对话中检索组织知识。

**PoC 范围控制**（文档 7.1.5）：硬编码，无 UI，无自动化审批流。

**非目标**：不做管理界面，不做权限审批流，不做自动化文档入库管道。

---

## 2. 架构

```
deer-flow/
├── governance/                     # 自建治理层
│   └── kb_mcp/                     # 知识库 MCP Server
│       ├── pyproject.toml          # 独立 Python 包（uv 管理）
│       ├── server.py               # FastMCP 入口，暴露 MCP tools
│       ├── embedding.py            # 火山方舟 Doubao Embedding 客户端
│       ├── store.py                # ChromaDB 存储层（CRUD + 检索）
│       ├── config.py               # 配置（API Key、端口、路径）
│       └── data/                   # ChromaDB 持久化（gitignored）
│
├── extensions_config.json          # 注册 kb-mcp 为 MCP Server
└── Makefile                        # kb-mcp 启动命令
```

**数据流**：

```
Agent → DeerFlow MCP Client → kb-mcp :8101 (SSE) → ChromaDB + Doubao Embedding
```

kb-mcp 作为独立 Python 进程运行在 :8101，通过 SSE 传输与 DeerFlow 通信。DeerFlow 侧不改任何代码，只在 `extensions_config.json` 加一条 MCP Server 注册。

---

## 3. MCP Tool 接口

kb-mcp 暴露 3 个 MCP tool。DeerFlow 自动发现并注入 Agent 工具列表。

### 3.1 search_knowledge — 知识检索

```python
def search_knowledge(
    query: str,              # 检索问题
    level: str = "auto",    # "company" | "position" | "personal" | "auto"
    top_k: int = 5           # 返回条数
) -> list[dict]:
    """
    返回: [
        {
            "content": str,        # 匹配的文本片段
            "source_file": str,    # 来源文件名
            "line_range": str,     # 行号范围（如 "12-28"）
            "level": str,          # 所属层级
            "score": float         # 相似度分数
        }
    ]
    """
```

`level="auto"` 时按调用者角色自动选择可见层级（PoC 阶段硬编码为检索所有层）。

### 3.2 add_document — 文档入库

```python
def add_document(
    content: str,            # 文档内容
    source_file: str,        # 来源文件名
    level: str,              # "company" | "position" | "personal"
    metadata: dict = {}      # 附加标签（如岗位名、作者）
) -> dict:
    """
    返回: {"id": str, "status": "ok", "collection": str}
    """
```

### 3.3 list_collections — 列出知识分层

```python
def list_collections() -> list[dict]:
    """
    返回: [
        {"level": "company", "collection_name": "company", "document_count": 42},
        {"level": "position", "collection_name": "position:developer", "document_count": 15},
        {"level": "personal", "collection_name": "personal:wangguodong", "document_count": 8}
    ]
    """
```

---

## 4. 知识分层结构

三层结构（文档 5.1.2 要求），对应 ChromaDB 的 3 类 collection：

| 层级 | collection 命名 | 可见性 | 说明 |
|------|----------------|--------|------|
| 公司级 | `company` | 全员工 | 公司制度、流程、通用知识 |
| 岗位级 | `position:{岗位名}` | 特定岗位 | 岗位专属知识（如 `position:developer`） |
| 个人级 | `personal:{user_id}` | 仅本人 | 个人分身资料、私有知识 |

**来源追溯**（文档 5.1.2 要求）：每条检索结果附带 `source_file` 和 `line_range`，满足"检索结果附带行号与文件名"的要求。入库时将文档按段落切分，记录每段在原文中的行号范围。

---

## 5. Embedding 与存储

### 5.1 火山方舟 Doubao Embedding

- API 端点：`https://ark.cn-beijing.volces.com/api/v3/embeddings`
- 模型名：`doubao-embedding-text-240715`（或当前可用版本）
- 认证：`VOLCENGINE_API_KEY` 环境变量
- 向量维度：2048
- 请求格式：OpenAI 兼容（`{"model": "...", "input": "..."}`）

### 5.2 ChromaDB 内嵌

- 持久化路径：`governance/kb_mcp/data/chroma_db/`
- SDK：`chromadb.PersistentClient(path=...)`，不启动独立服务进程
- distance metric：cosine
- 每个 collection 存储向量 + metadata（source_file, line_range, level, ...）

### 5.3 降级策略（文档 7.1.4 要求）

- Embedding API 超时 10 秒 → 返回空结果 + 日志告警，不阻断 Agent 主流程
- ChromaDB 查询异常 → 同上降级，返回空结果
- kb-mcp 服务不可用 → DeerFlow MCP Client 自动跳过该 tool，Agent 不崩溃

---

## 6. DeerFlow 接入

零代码侵入，纯配置接入。

### 6.1 extensions_config.json 注册

```json
{
  "mcpServers": {
    "kb-mcp": {
      "enabled": true,
      "type": "sse",
      "url": "http://localhost:8101/sse",
      "description": "RAG 知识库（公司/岗位/个人三层）",
      "tool_call_timeout": 30
    }
  }
}
```

DeerFlow 会自动发现 kb-mcp 暴露的 3 个 MCP tool，注入 Agent 工具列表。Agent 在对话中需要检索知识时，自动调用 `search_knowledge`。

### 6.2 启动方式

```bash
# 单独启动 kb-mcp
cd governance/kb_mcp && uv run python server.py

# DeerFlow 重启后会自动连接 kb-mcp
# 通过 Gateway API 更新 MCP 配置后无需重启（DeerFlow 检测 extensions_config.json 变化自动重载）
```

---

## 7. 技术选型

| 组件 | 选型 | 理由 |
|------|------|------|
| MCP Server 框架 | `mcp` Python SDK（`FastMCP`） | 官方 SDK，与 DeerFlow 的 `langchain-mcp-adapters` 兼容 |
| 向量存储 | ChromaDB 内嵌（`chromadb.PersistentClient`） | 轻量，无额外服务进程，文档首选 |
| Embedding | 火山方舟 Doubao Embedding | 文档首选，与 Chat 凭证统一 |
| 传输协议 | SSE（HTTP） | 独立服务，多进程安全，符合文档 :8101 架构 |
| 包管理 | `uv` | 与 DeerFlow 后端一致 |

---

## 8. PoC 验证标准

1. kb-mcp 能启动并响应 SSE 连接（`curl http://localhost:8101/sse` 返回 200）
2. 通过 `add_document` 入库一篇测试文档，ChromaDB 持久化成功
3. Agent 对话中能自动调用 `search_knowledge` 并返回包含 `source_file` 和 `line_range` 的结果
4. Embedding API 超时时 kb-mcp 返回空结果，不崩溃 Agent
5. `list_collections` 正确返回三层 collection 及文档计数

---

## 9. 后续阶段（不在本次 PoC 范围内）

- Auth/RBAC 中间件：控制谁能访问哪个层级的知识
- Audit 审计中间件：记录谁检索了什么
- Eval API：用固定测试样本集评估检索质量
- 文档自动入库管道（目录扫描 + 解析 + 切分）
- 管理 UI
