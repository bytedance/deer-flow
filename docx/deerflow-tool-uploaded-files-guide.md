# DeerFlow Tool 获取前端上传文件 — 完全指南

> 目标读者：要在 DeerFlow 里写一个 `@tool`，需要让这个 tool 访问到前端聊天框里用户上传的文件（PDF / 图片 / 文本等）。
>
> 一句话总结：**`Runtime` 是钥匙，物理路径在 `runtime.state["thread_data"]["uploads_path"]`，虚拟路径走 `resolve_and_validate_user_data_path`，转换后的 markdown 自动伴生在原文件旁边。** 其它"上传文件在哪、怎么读、按什么路径"都已经被 DeerFlow 现成的中件间、sandbox 工具、`uploads.manager` 模块打点好了——你只管调。

---

## 一、文件存哪、谁负责（先把全景钉死）

```
前端 FormData
   │  POST /api/threads/{tid}/uploads        (gateway/routers/uploads.py)
   ▼
{base_dir}/users/{user_id}/threads/{tid}/user-data/uploads/                       ← 物理路径
{base_dir}/users/{user_id}/threads/{tid}/user-data/uploads/foo.pdf.md            ← 自动转换的伴生 .md

前端发下一条消息时
   │  HumanMessage.additional_kwargs.files = [
   │      {"filename": "foo.pdf", "size": 12345, "path": "/mnt/user-data/uploads/foo.pdf", ...}
   │  ]
   ▼
UploadsMiddleware (agents/middlewares/uploads_middleware.py)
   │  ├─ 把 <uploaded_files> 块塞进 HumanMessage.content（LLM 看到清单）
   │  └─ state["uploaded_files"] = 新文件列表
   ▼
ThreadDataMiddleware (agents/middlewares/thread_data_middleware.py)
   │  state["thread_data"] = {
   │      "workspace_path": ".../user-data/workspace",
   │      "uploads_path":   ".../user-data/uploads",   ← 你要的主路径
   │      "outputs_path":   ".../user-data/outputs",
   │  }
   ▼
你的 tool  ← 这里
```

**两个最关键的事实**：

1. 物理目录是 `runtime.state["thread_data"]["uploads_path"]`（已经按 user × thread 隔离好）
2. 虚拟路径是 `/mnt/user-data/uploads/{filename}`，LLM 在 prompt 里就是这么写的

涉及的代码位置（供你深挖）：

| 模块 | 路径 |
|---|---|
| 上传目录管理 | `backend/packages/harness/deerflow/uploads/manager.py` |
| 中件间：注入 `<uploaded_files>` | `backend/packages/harness/deerflow/agents/middlewares/uploads_middleware.py` |
| 中件间：注入 `thread_data` | `backend/packages/harness/deerflow/agents/middlewares/thread_data_middleware.py` |
| ThreadState schema | `backend/packages/harness/deerflow/agents/thread_state.py` |
| 路径解析 + 越界校验 | `backend/packages/harness/deerflow/sandbox/tools.py`（`get_thread_data` / `resolve_and_validate_user_data_path` / `validate_local_tool_path`） |
| 路径常量 | `backend/packages/harness/deerflow/config/paths.py`（`VIRTUAL_PATH_PREFIX = "/mnt/user-data"`，`sandbox_uploads_dir`） |
| Tool `Runtime` 类型 | `backend/packages/harness/deerflow/tools/types.py` |
| 参考实现 | `view_image_tool.py`、`present_file_tool.py`（同目录 `tools/builtins/`） |

---

## 二、4 种拿法，按"工具签名"选

### 拿法 A — `Runtime` 注入（推荐：跟 `view_image_tool` / `present_file_tool` 一脉相承）

`Runtime` 是 LangChain 的 `@tool` 装饰器**自动注入**的参数，只要函数签名里写 `runtime: Runtime` 就有。`tools/types.py` 里已经定义好：

```python
# packages/harness/deerflow/tools/types.py
Runtime = ToolRuntime[dict[str, Any], ThreadState]
```

#### A1. 拿"本轮新上传的文件清单" + "uploads 物理路径"

```python
from langchain.tools import tool
from deerflow.tools.types import Runtime


@tool
def summarize_my_uploads(runtime: Runtime) -> str:
    """总结用户本轮上传的所有文件（如果有）。"""
    state = runtime.state or {}
    thread_data = state.get("thread_data") or {}
    uploads_path = thread_data.get("uploads_path")

    if not uploads_path:
        return "Error: thread_data.uploads_path not available"

    uploaded = state.get("uploaded_files") or []   # 本轮新上传（UploadsMiddleware 写入）
    if not uploaded:
        return f"No files were uploaded in this turn. uploads dir: {uploads_path}"

    # uploaded 的每条形如 {"filename","size","path","extension","outline","outline_preview"}
    lines = [f"uploads_path: {uploads_path}", f"newly uploaded ({len(uploaded)}):"]
    for f in uploaded:
        lines.append(f"  - {f['filename']} ({f['size']} bytes)")
    return "\n".join(lines)
```

`uploaded_files` 的字段（来自 `uploads_middleware.py:177-184`）：

| 字段 | 含义 |
|---|---|
| `filename` | 真实文件名（已 sanitize） |
| `size` | 字节数 |
| `path` | 虚拟路径 `/mnt/user-data/uploads/{filename}` |
| `extension` | 后缀（含 `.`） |
| `outline` | 可选，PDF/DOCX 转换后的 markdown 提取的标题列表（LLM 用来定位章节） |
| `outline_preview` | 可选，没有 outline 时给的前 5 行预览 |

#### A2. 拿"线程所有历史文件"（不只是本轮）

```python
import os
from langchain.tools import tool
from deerflow.tools.types import Runtime


@tool
def list_all_uploaded(runtime: Runtime) -> str:
    """列出本线程历史上所有用户上传过的文件。"""
    thread_data = (runtime.state or {}).get("thread_data") or {}
    uploads_dir = thread_data.get("uploads_path")
    if not uploads_dir or not os.path.isdir(uploads_dir):
        return f"No uploads directory: {uploads_dir}"

    files = sorted(
        (e for e in os.scandir(uploads_dir) if e.is_file(follow_symlinks=False)),
        key=lambda e: e.name,
    )
    if not files:
        return "Uploads directory is empty."

    lines = [f"uploads_path: {uploads_dir}"]
    for entry in files:
        st = entry.stat(follow_symlinks=False)
        size_kb = st.st_size / 1024
        size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"
        lines.append(f"  - {entry.name} ({size_str})")
    return "\n".join(lines)
```

> `UploadsMiddleware` 自己在 `before_agent` 里就做过"扫描历史文件并加 outline"，如果你想直接复用那段逻辑，可以反过来 `import` 它——但通常自己 `os.scandir` 反而更轻。

#### A3. 拿"LLM 告诉你的某个具体文件"（推荐：最常用）

LLM 经常会说"请读一下 `/mnt/user-data/uploads/report.pdf`"。你的 tool 拿到这个虚拟路径后，**必须**用 sandbox 工具把它解析成 host 路径，否则就走出了 sandbox 边界。

```python
from pathlib import Path
from langchain.tools import tool
from deerflow.sandbox.tools import (
    get_thread_data,
    resolve_and_validate_user_data_path,
    validate_local_tool_path,
)
from deerflow.tools.types import Runtime


@tool
def read_uploaded_file(virtual_path: str, runtime: Runtime) -> str:
    """读取用户在 DeerFlow 前端上传的文件。

    Args:
        virtual_path: 形如 /mnt/user-data/uploads/foo.pdf 的沙箱虚拟路径。
    """
    thread_data = get_thread_data(runtime)
    if thread_data is None:
        return "Error: thread_data not available in runtime state"

    # 1) 安全校验：路径必须在 /mnt/user-data/ 内
    try:
        validate_local_tool_path(virtual_path, thread_data, read_only=True)
    except PermissionError as e:
        return f"Error: {e}"

    # 2) 把虚拟路径解析成 host 真实路径
    try:
        actual_path = resolve_and_validate_user_data_path(virtual_path, thread_data)
    except (PermissionError, ValueError) as e:
        return f"Error: {e}"

    p = Path(actual_path)
    if not p.is_file():
        return f"Error: File not found: {virtual_path}"

    # 3) 优先读 .md 伴生文件（PDF/DOCX 已转换），没有就回退原文件
    md = p.with_suffix(".md")
    target = md if md.is_file() else p
    return target.read_text(encoding="utf-8", errors="replace")
```

这就是 `view_image_tool` 同款写法。安全闸门在 `validate_local_tool_path`，真实路径解析在 `resolve_and_validate_user_data_path`，两者**缺一不可**。

---

### 拿法 B — `InjectedToolArg` + `RunnableConfig`（社区工具 / Dify 风格）

如果你写的是**社区工具**（不想接 `Runtime`，参考 `packages/zens/zens/community/dify/router.py` 那种），可以用：

```python
from typing import Annotated
from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg

from deerflow.runtime.user_context import get_effective_user_id
from deerflow.uploads.manager import get_uploads_dir, list_files_in_dir


@tool
def community_list_uploads(
    config: Annotated[RunnableConfig, InjectedToolArg] = None,
) -> str:
    """（社区工具风格）列出本线程已上传的所有文件。"""
    configurable = (config or {}).get("configurable", {})
    thread_id = configurable.get("thread_id") or "default"

    user_id = get_effective_user_id()                          # contextvar，gateway 自动设
    uploads_dir = get_uploads_dir(thread_id)                   # 自动用 user_id 拼路径
    result = list_files_in_dir(uploads_dir)
    if not result["files"]:
        return f"No files in {uploads_dir}"

    lines = [f"{len(result['files'])} file(s) in uploads/"]
    for f in result["files"]:
        lines.append(f"  - {f['filename']} ({f['size']} bytes)")
    return "\n".join(lines)
```

要点：

- `config: Annotated[RunnableConfig, InjectedToolArg]` 是 LangChain 的**注入**字段——LLM 看不到，运行时由 LangChain 自动填
- `get_effective_user_id()` 走 contextvar，gateway 在鉴权后自动写入；本地用 `DeerFlowClient` 时也兼容
- 适合：完全无状态的"远程服务风格"工具

---

### 拿法 C — 不带任何 Runtime 元数据，用纯路径

如果你的 tool 是**完全在 tool 进程内自洽运行**（比如跑在 Dify 容器、ACP 子进程里），拿不到 `Runtime`，那只能要求调用方把 `thread_id` 当参数传进来：

```python
from langchain.tools import tool
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.uploads.manager import get_uploads_dir, list_files_in_dir


@tool
def external_process_uploads(thread_id: str) -> str:
    """（外部工具）按 thread_id 读取 uploads 目录。"""
    uploads_dir = get_uploads_dir(thread_id)
    result = list_files_in_dir(uploads_dir)
    return f"uploads_dir={uploads_dir}, count={result['count']}"
```

⚠️ 这种写法**依赖于调用方传的是真实的 thread_id**——`get_uploads_dir` 内部会做 `validate_thread_id` 校验，不合法会抛 `ValueError`。

---

## 三、五个常见的"小坑"

| 坑 | 症状 | 解决 |
|---|---|---|
| 直接用 LLM 给的 `/mnt/user-data/...` 字符串当 host 路径 `open()` | 找不到文件 / 路径越界 | 一律 `resolve_and_validate_user_data_path(virtual_path, thread_data)` |
| PDF 上传后 `read_file` 读出二进制乱码 | 没有走转换管线 | DeerFlow 已经在上传时**自动**生成 `foo.pdf.md`；你的 tool 应优先 `p.with_suffix(".md").read_text()` |
| 多轮对话后 LLM 不再记得"哪些文件可用" | 提示词里没文件清单 | 那是 `UploadsMiddleware` 的事——`uploaded_files` 列表每轮都会重算；**不要自己缓存** |
| 想用 `uploaded_files` 但 `runtime.state` 为 `None` | tool 没跑在 LangGraph runtime 里 | 检查 `@tool` 的签名里 `runtime: Runtime` 是不是首位非默认参数；或者用拿法 B/C |
| 用户在沙箱里产生了"输出文件"想去推 | 用了 `uploads_path` | **不对**——`/mnt/user-data/uploads` 只放用户上传的；agent 自己的产出应该写 `/mnt/user-data/outputs`，用 `state.thread_data["outputs_path"]` + `present_file_tool` |

---

## 四、决策树

```
你的 tool 是在 lead_agent / subagent 流程里跑的吗？
  ├─ 是 → 签名加 runtime: Runtime
  │        ├─ LLM 给了虚拟路径？      → 拿法 A3（resolve + validate + read）
  │        ├─ 想处理"本轮新上传"？    → 拿法 A1（state["uploaded_files"]）
  │        └─ 想处理"本线程所有历史"？→ 拿法 A2（os.scandir(thread_data["uploads_path"])）
  │
  └─ 否（社区/外部工具，Dify / 自建子服务）
       ├─ 能拿到 RunnableConfig？  → 拿法 B（InjectedToolArg + get_effective_user_id）
       └─ 啥都拿不到？            → 拿法 C（thread_id 显式当参数）
```

---

## 五、完整可跑模板（最常用：拿法 A3）

```python
# backend/packages/harness/deerflow/tools/builtins/read_upload_tool.py
from __future__ import annotations

from pathlib import Path

from langchain.tools import tool

from deerflow.sandbox.tools import (
    get_thread_data,
    resolve_and_validate_user_data_path,
    validate_local_tool_path,
)
from deerflow.tools.types import Runtime


@tool("read_uploaded_file", parse_docstring=True)
def read_uploaded_file_tool(virtual_path: str, runtime: Runtime) -> str:
    """读取 DeerFlow 前端上传的文件。

    接受 /mnt/user-data/uploads/* 形式的虚拟路径（用户在 lead_agent
    提示词里看到的也是这个路径）。如果是 PDF/DOCX 等可转换类型，
    会自动读取上传时生成的同名 .md 伴生文件。

    Args:
        virtual_path: 虚拟路径，例如 ``/mnt/user-data/uploads/report.pdf``。
    """
    thread_data = get_thread_data(runtime)
    if thread_data is None:
        return "Error: thread_data not available in runtime state"

    # 1) 路径必须在 /mnt/user-data 内（防越界）
    try:
        validate_local_tool_path(virtual_path, thread_data, read_only=True)
    except PermissionError as e:
        return f"Error: invalid path: {e}"

    # 2) 虚拟 → host 真实路径
    try:
        actual = resolve_and_validate_user_data_path(virtual_path, thread_data)
    except (PermissionError, ValueError) as e:
        return f"Error: cannot resolve path: {e}"

    p = Path(actual)
    if not p.is_file():
        return f"Error: file not found: {virtual_path}"

    # 3) 优先读 .md 伴生文件
    md = p.with_suffix(".md")
    target = md if md.is_file() else p
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"Error reading file: {e}"

    # 4) 截断到合理长度（避免一次性塞爆 LLM 上下文）
    return content[:200_000]
```

注册：

```python
# tools/builtins/__init__.py
from .read_upload_tool import read_uploaded_file_tool
```

---

## 六、参考资源

- 现有同类工具写法：`view_image_tool.py`、`present_file_tool.py`（路径 `backend/packages/harness/deerflow/tools/builtins/`）
- Dify 风格社区工具：`packages/zens/zens/community/dify/router.py`（演示 `InjectedToolArg` 拿法）
- 上传接口契约：`backend/app/gateway/routers/uploads.py`
- 流式输出（要给"用户读文件"过程加打字机效果）：见 `docx/deerflow-tool-streaming-output-guide.md`（如未补建可按"工具里用 `get_stream_writer()` + 客户端开 `stream_mode=["values","custom"]`"的思路实现）
