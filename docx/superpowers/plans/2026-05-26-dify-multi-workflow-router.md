# Dify 多工作流路由 Tool 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将单个 `dify_chat_tool` 拆分为多个独立 workflow tool，支持 blocking/streaming 两种 response_mode。

**Architecture:** 每个 Dify 工作流对应一个独立 `@tool`，通过 `router.py` 统一调用逻辑，按 `config.yaml` 中 `response_mode` 字段选择 blocking 或 streaming。日志按 workflow 分离，对话缓存按 `(user_id, thread_id, workflow_name)` 独立维护。

**Tech Stack:** Python 3.12, httpx, LangChain `@tool`, Pydantic

---

## 文件结构

```
backend/packages/zens/zens/community/dify/
  ├── __init__.py                          # 导出所有 workflow tools
  ├── client.py                            # DifyClient（新增 chat_stream，返回 chunks+conversation_id）
  ├── router.py                           # 新增：统一调用入口
  ├── workflows/
  │   ├── __init__.py                     # 新增：workflows 包
  │   ├── aml.py                          # 新增：dify_aml_tool
  │   ├── knowledge.py                    # 新增：dify_knowledge_tool
  │   └── general.py                      # 新增：dify_general_tool
  └── tools.py                            # 废弃（将被移除）
```

**测试文件：**
```
backend/packages/zens/tests/test_dify_workflow_tools.py  # 新增：workflow tool 测试
backend/packages/zens/tests/test_dify_streaming.py      # 新增：streaming 模式测试
backend/packages/zens/tests/test_dify_tool.py            # 修改：移除旧 dify_chat_tool 引用
```

**config.yaml 示例：**
```
tools:
  - name: dify_aml
    use: zens.community.dify.workflows.aml:dify_aml_tool
    group: community
    api_key: $DIFY_AML_API_KEY
    base_url: http://localhost:8000
    response_mode: streaming
```

---

## Task 1: DifyClient 新增 streaming 支持

**Files:**
- Modify: `backend/packages/zens/zens/community/dify/client.py`

- [ ] **Step 1: 写 streaming 测试**

```python
# backend/packages/zens/tests/test_dify_streaming.py
import pytest
from unittest.mock import patch


class FakeStreamResponse:
    def __init__(self, lines_data):
        self._lines = lines_data
        self._iter = iter(lines_data)

    @property
    def is_success(self):
        return True

    def iter_lines(self):
        return self._iter


def test_chat_stream_yields_chunks_and_conversation_id():
    from zens.community.dify.client import DifyClient

    client = DifyClient(api_key="test-key", base_url="http://localhost:8000")

    mock_lines = [
        b'event: message\ndata: {"answer": "hel", "conversation_id": "conv-1", "message_id": "msg-1"}\n',
        b'event: message\ndata: {"answer": "lo", "conversation_id": "conv-1", "message_id": "msg-2"}\n',
        b'event: message\ndata: {"answer": " world", "conversation_id": "conv-1", "message_id": "msg-3"}\n',
    ]

    with patch("zens.community.dify.client.httpx") as mock_httpx:
        mock_response = FakeStreamResponse(mock_lines)
        mock_httpx.post.return_value = mock_response

        chunks, conv_id = client.chat_stream(query="hello", conversation_id="", user="test")
        assert chunks == ["hel", "lo", " world"]
        assert conv_id == "conv-1"
```

- [ ] **Step 2: 运行测试，确认 FAIL**

```
cd backend && PYTHONPATH=. uv run pytest packages/zens/tests/test_dify_streaming.py::test_chat_stream_yields_chunks_and_conversation_id -v
```
Expected: FAIL — `DifyClient.chat_stream` not defined

- [ ] **Step 3: 在 client.py 新增 chat_stream 方法**

在 `DifyClient` 类中添加：

```python
def chat_stream(
    self,
    query: str,
    conversation_id: str,
    user: str,
    timeout: float = 60.0,
) -> tuple[list[str], str]:
    """Streaming 模式：解析 SSE lines，返回 (chunks, conversation_id)。

    Dify streaming API 返回 SSE lines，格式：
        event: message
        data: {"answer": "...", "conversation_id": "...", "message_id": "..."}

    Returns:
        tuple: (chunks: list[str], conversation_id: str)
            chunks — 所有 answer 片段按顺序拼接的 list
            conversation_id — 最后一个非空 conversation_id，供 router 缓存
    """
    logger.debug("Dify streaming request: query=%r, conversation_id=%r, user=%r",
                 query, conversation_id, user)
    url = f"{self.base_url}/v1/chat-messages"
    headers = {
        "Authorization": f"Bearer {self.api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "inputs": {},
        "query": query,
        "response_mode": "streaming",
        "conversation_id": conversation_id,
        "user": user,
        "files": [],
    }

    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=timeout)
    except httpx.TimeoutException:
        logger.error("Dify streaming request timed out (url=%s)", url)
        raise DifyAPIError(0, "Request to Dify timed out")

    if not response.is_success:
        try:
            error_body = response.json()
            message = error_body.get("message", response.text)
        except httpx.HTTPError:
            message = response.text or "Unknown error"
        logger.error("Dify streaming API error: status=%d, message=%s",
                     response.status_code, message)
        raise DifyAPIError(response.status_code, message)

    conversation_id_result = [""]
    chunks = []

    for line in response.iter_lines():
        if not line.startswith(b"data: "):
            continue
        data_str = line.decode("utf-8")[6:].strip()
        if not data_str:
            continue
        import json
        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            continue
        answer = data.get("answer", "")
        if answer:
            chunks.append(answer)
        if data.get("conversation_id"):
            conversation_id_result[0] = data["conversation_id"]

    logger.info("Dify streaming completed: chunks=%d, conversation_id=%s",
                len(chunks), conversation_id_result[0])
    return chunks, conversation_id_result[0]
```

- [ ] **Step 4: 运行测试，确认 PASS**

```
cd backend && PYTHONPATH=. uv run pytest packages/zens/tests/test_dify_streaming.py::test_chat_stream_yields_chunks_and_conversation_id -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd backend && git add packages/zens/tests/test_dify_streaming.py packages/zens/zens/community/dify/client.py
git commit -m "feat(dify): add DifyClient.chat_stream returning (chunks, conversation_id)"
```

---

## Task 2: 创建 router.py 统一调用入口

**Files:**
- Create: `backend/packages/zens/zens/community/dify/router.py`

- [ ] **Step 1: 创建 router.py**（直接实现，无需预先写测试）

```python
"""Dify 多工作流路由统一入口。"""
import logging
from collections import OrderedDict
from pathlib import Path
from threading import Lock
from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg

from deerflow.config import get_app_config
from deerflow.runtime.user_context import get_effective_user_id

from zens.community.dify.client import DifyAPIError, DifyClient

_MAX_CONVERSATION_CACHE = 1000
_conversation_ids: OrderedDict[str, str] = OrderedDict()
_lock = Lock()

_workflow_loggers: dict[str, logging.Logger] = {}


def _get_cache_key(tool_name: str, config: RunnableConfig | None) -> str:
    user_id = get_effective_user_id()
    thread_id = _get_thread_id(config)
    return f"{user_id}:{thread_id}:{tool_name}"


def _get_thread_id(config: RunnableConfig | None) -> str:
    if config is None:
        return "default"
    configurable = config.get("configurable") or {}
    thread_id = configurable.get("thread_id")
    if thread_id is None:
        return "default"
    return str(thread_id)


def _get_cached_conversation(cache_key: str) -> str:
    with _lock:
        if cache_key in _conversation_ids:
            _conversation_ids.move_to_end(cache_key)
            return _conversation_ids[cache_key]
        return ""


def _cache_conversation(cache_key: str, conversation_id: str) -> None:
    with _lock:
        _conversation_ids[cache_key] = conversation_id
        _conversation_ids.move_to_end(cache_key)
        if len(_conversation_ids) > _MAX_CONVERSATION_CACHE:
            _conversation_ids.popitem(last=False)


def _get_tool_config(tool_name: str) -> "ToolConfigResult":
    """从 config.yaml 读取指定 tool_name 的配置。"""
    config = get_app_config().get_tool_config(tool_name)
    if config is None:
        raise DifyAPIError(0, f"Tool '{tool_name}' is not configured in config.yaml")
    api_key = config.model_extra.get("api_key") if config.model_extra else None
    if not api_key:
        raise DifyAPIError(0, f"api_key not configured for tool '{tool_name}'")
    base_url = (config.model_extra.get("base_url") if config.model_extra else None) or "http://localhost:8000"
    response_mode = (config.model_extra.get("response_mode") if config.model_extra else None) or "blocking"
    return ToolConfigResult(api_key=api_key, base_url=base_url, response_mode=response_mode)


class ToolConfigResult:
    def __init__(self, api_key: str, base_url: str, response_mode: str = "blocking"):
        self.api_key = api_key
        self.base_url = base_url
        self.response_mode = response_mode


def _get_workflow_logger(tool_name: str) -> logging.Logger:
    if tool_name not in _workflow_loggers:
        logger = logging.getLogger(f"zens.community.dify.{tool_name}")
        logger.setLevel(logging.DEBUG)
        _logs_dir = Path(__file__).resolve().parent.parent.parent.parent / "logs"
        _logs_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(
            _logs_dir / f"dify_{tool_name}.log", mode="a", encoding="utf-8"
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
        )
        logger.addHandler(handler)
        _workflow_loggers[tool_name] = logger
    return _workflow_loggers[tool_name]


def invoke_workflow(
    tool_name: str,
    query: str,
    config: Annotated[RunnableConfig, InjectedToolArg] = None,
) -> str:
    """统一工作流调用入口。按 response_mode 路由到 blocking 或 streaming。"""
    logger = _get_workflow_logger(tool_name)
    cache_key = _get_cache_key(tool_name, config)
    conversation_id = _get_cached_conversation(cache_key)
    user_id = get_effective_user_id()
    user = f"deerflow_{user_id}"

    logger.info("invoke_workflow: tool=%s, query=%r, conversation_id=%r", tool_name, query, conversation_id)

    tool_cfg = _get_tool_config(tool_name)
    client = DifyClient(api_key=tool_cfg.api_key, base_url=tool_cfg.base_url)

    if tool_cfg.response_mode == "streaming":
        chunks, conv_id = client.chat_stream(query=query, conversation_id=conversation_id, user=user)
        full_answer = "".join(chunks)
        if conv_id:
            _cache_conversation(cache_key, conv_id)
        logger.info("invoke_workflow streaming completed: answer=%r, conversation_id=%s",
                   full_answer[:50] if full_answer else "", conv_id)
        return full_answer

    response = client.chat(query=query, conversation_id=conversation_id, user=user)
    if response.conversation_id:
        _cache_conversation(cache_key, response.conversation_id)
    logger.info("invoke_workflow blocking completed: answer=%r", response.answer[:50] if response.answer else "")
    return response.answer
```

- [ ] **Step 2: Commit**

```bash
cd backend && git add packages/zens/zens/community/dify/router.py
git commit -m "feat(dify): add router.py unified workflow invoker"
```

---

## Task 3: 创建各 workflow tool 文件

**Files:**
- Create: `backend/packages/zens/zens/community/dify/workflows/__init__.py`
- Create: `backend/packages/zens/zens/community/dify/workflows/aml.py`
- Create: `backend/packages/zens/zens/community/dify/workflows/knowledge.py`
- Create: `backend/packages/zens/zens/community/dify/workflows/general.py`
- Modify: `backend/packages/zens/zens/community/dify/__init__.py`
- Test: `backend/packages/zens/tests/test_dify_workflow_tools.py`

- [ ] **Step 1: 创建 workflows/__init__.py**

```python
"""Dify workflow tools."""
from zens.community.dify.workflows.aml import dify_aml_tool
from zens.community.dify.workflows.general import dify_general_tool
from zens.community.dify.workflows.knowledge import dify_knowledge_tool

__all__ = ["dify_aml_tool", "dify_knowledge_tool", "dify_general_tool"]
```

- [ ] **Step 2: 创建 workflows/aml.py**

```python
"""反洗钱（AML）Dify 工作流 Tool。"""
from typing import Annotated

from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg

from zens.community.dify.router import invoke_workflow


@tool("dify_aml", parse_docstring=True)
def dify_aml_tool(
    query: str,
    config: Annotated[RunnableConfig, InjectedToolArg] = None,
) -> str:
    """反洗钱工作流（AML）。

    当用户问到以下场景时调用本工具：
    - 可疑交易识别 / 交易监控 / 洗钱风险评估
    - 金融机构合规 / 监管要求（反洗钱相关）
    - 客户尽职调查（CDD）/ 受益人识别 / 交易筛选
    - 制裁名单筛查 / PEP（PPE 政治敏感人士）核查

    Args:
        query: 用户的 AML 相关问题或交易描述。
    """
    return invoke_workflow("dify_aml", query, config)
```

- [ ] **Step 3: 创建 workflows/knowledge.py**

```python
"""知识问答 Dify 工作流 Tool。"""
from typing import Annotated

from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg

from zens.community.dify.router import invoke_workflow


@tool("dify_knowledge", parse_docstring=True)
def dify_knowledge_tool(
    query: str,
    config: Annotated[RunnableConfig, InjectedToolArg] = None,
) -> str:
    """知识问答工作流。

    当用户问到以下场景时调用本工具：
    - 知识库检索 / 百科查询 / 常识问题
    - 文档查阅 / 资料查找 / 知识获取
    - 产品说明 / 操作指南 / 业务介绍

    Args:
        query: 用户的知识性或百科类问题。
    """
    return invoke_workflow("dify_knowledge", query, config)
```

- [ ] **Step 4: 创建 workflows/general.py**

```python
"""通用 Dify 工作流 Tool。"""
from typing import Annotated

from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg

from zens.community.dify.router import invoke_workflow


@tool("dify_general", parse_docstring=True)
def dify_general_tool(
    query: str,
    config: Annotated[RunnableConfig, InjectedToolArg] = None,
) -> str:
    """通用对话工作流。

    当用户的问题不属于反洗钱（AML）或知识问答范围时，调用本工具。
    适用于日常对话、闲聊、通用问题解答等场景。

    Args:
        query: 用户的通用问题或对话内容。
    """
    return invoke_workflow("dify_general", query, config)
```

- [ ] **Step 5: 更新 __init__.py 导出**

```python
"""Dify community tool for DeerFlow zens extension."""

from zens.community.dify.workflows.aml import dify_aml_tool
from zens.community.dify.workflows.general import dify_general_tool
from zens.community.dify.workflows.knowledge import dify_knowledge_tool

__all__ = ["dify_aml_tool", "dify_knowledge_tool", "dify_general_tool"]
```

- [ ] **Step 6: 写 workflow tool 加载测试**

```python
# backend/packages/zens/tests/test_dify_workflow_tools.py
import pytest
from unittest.mock import patch


def test_aml_tool_loads():
    from zens.community.dify.workflows.aml import dify_aml_tool
    assert dify_aml_tool.name == "dify_aml"
    assert "反洗钱" in dify_aml_tool.description


def test_knowledge_tool_loads():
    from zens.community.dify.workflows.knowledge import dify_knowledge_tool
    assert dify_knowledge_tool.name == "dify_knowledge"


def test_general_tool_loads():
    from zens.community.dify.workflows.general import dify_general_tool
    assert dify_general_tool.name == "dify_general"


def test_all_tools_have_query_arg():
    from zens.community.dify.workflows.aml import dify_aml_tool
    from zens.community.dify.workflows.knowledge import dify_knowledge_tool
    from zens.community.dify.workflows.general import dify_general_tool
    import inspect
    for t in [dify_aml_tool, dify_knowledge_tool, dify_general_tool]:
        sig = inspect.signature(t.invoke)
        assert "input" in sig.parameters, f"{t.name} missing 'input' param"
```

- [ ] **Step 7: 运行测试**

```
cd backend && PYTHONPATH=. uv run pytest packages/zens/tests/test_dify_workflow_tools.py -v
```
Expected: PASS

- [ ] **Step 8: Commit**

```bash
cd backend && git add packages/zens/zens/community/dify/workflows/
git add packages/zens/zens/community/dify/__init__.py
git add packages/zens/tests/test_dify_workflow_tools.py
git commit -m "feat(dify): add separate workflow tools (aml, knowledge, general)"
```

---

## Task 4: 废弃旧 tools.py

**Files:**
- Modify: `backend/packages/zens/tests/test_dify_tool.py` — 移除旧测试

- [ ] **Step 1: 确认旧测试内容并移除/更新**

检查 `packages/zens/tests/test_dify_tool.py`，移除所有对 `dify_chat_tool` 的引用。将文件内容调整为不依赖 `tools.py` 的独立测试（如 `test_dify_response_model`、`test_dify_api_error` 保持不变，因为它们测试的是 `client.py`）。

```python
# backend/packages/zens/tests/test_dify_tool.py — 移除 test_dify_chat_tool_no_api_key
# 移除 test_conversation_id_caching
# 保留 test_dify_response_model 和 test_dify_api_error
```

- [ ] **Step 2: 运行确认没有 dify_chat_tool 引用**

```
cd backend && PYTHONPATH=. uv run pytest packages/zens/tests/test_dify_tool.py -v
```
Expected: PASS（只保留 client.py 相关测试）

- [ ] **Step 3: Commit**

```bash
cd backend && git add packages/zens/tests/test_dify_tool.py
git commit -m "chore(dify): remove deprecated dify_chat_tool tests"
```

---

## 验收测试

- [ ] `PYTHONPATH=. uv run pytest packages/zens/tests/test_dify_workflow_tools.py packages/zens/tests/test_dify_streaming.py -v` — 全部 PASS
- [ ] `resolve_variable("zens.community.dify.workflows.aml:dify_aml_tool", BaseTool)` — 成功加载
- [ ] `cat backend/logs/dify_aml.log` — 存在且有内容
- [ ] `config.yaml` 中三个 tool 配置正确，`response_mode` 字段生效

---

**Plan complete.**