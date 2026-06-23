# Per-User Persistent Home Mount（`/mnt/user-home/`）设计

日期：2026-06-22
分支：`main`
状态：Draft（待用户 review）
关联：上游 issue [#2905](https://github.com/bytedance/deer-flow/issues/2905)（milestone 2.1.0，per-user skill mount）；本地原始提案 `docx/share-files/user-home-mount-proposal.md`

---

## 背景与目标

### 问题

DeerFlow 现有的按线程沙箱隔离对"属于用户而非线程"的文件粒度过细。今天，agent（或 skill）写入 `/mnt/user-data/{workspace,uploads,outputs}` 的所有内容都落在：

```
backend/.deer-flow/users/{user_id}/threads/{thread_id}/user-data/
```

线程结束或用户开新对话时，这些内容就消失了。

### 具体痛点（本地观察）

用户安装了一个自定义 skill（`skills/custom/obsidian-skills`），让 agent bootstrap 一个 Obsidian vault：

| 文件 | agent 放在哪 | 新会话能看到吗 |
|------|--------------|----------------|
| `SKILL.md` 定义 | `skills/custom/obsidian-skills/SKILL.md`（宿主磁盘） | ✅ 能 |
| `obsidian.tar.gz`、`notesmd-cli` 二进制 | `threads/{tid}/user-data/workspace/` | ❌ 不能 |
| `vault/`（Obsidian 笔记） | `threads/{tid}/user-data/{workspace,outputs}/vault/` | ❌ 不能 |
| `diary.md`、`2026-06-16.md` | `threads/{tid}/user-data/outputs/` | ❌ 不能 |

新会话的 `/mnt/user-data/workspace/` 是空的，agent 没有任何机制去发现或复用老线程的文件。

### 架构层根因

没有一等公民的 per-user 持久化挂载。现有分层隔离只有：

| 作用域 | 生命周期 | 路径 |
|--------|----------|------|
| 沙箱容器 | 每线程、临时 | Docker / AIO 容器 |
| `/mnt/user-data` | 每线程 | `users/{uid}/threads/{tid}/user-data/` |
| `/mnt/skills` | 每用户，但**只读** | `deer-flow/skills/` |
| `memory.json`、`USER.md`、自定义 agents | 每用户、持久化、**仅元数据** | `users/{uid}/{memory.json,USER.md,agents/}` |

per-user **文件**层是缺的。skills 是按设计只读的，memory 是文本，custom agents 是模板——三者都不给 agent 一个可写的、通用的、跨线程的家目录。

### 目标

- **G1.** 新增每用户、持久化、**可写**的目录，以稳定虚拟路径挂进沙箱（拟定为 `/mnt/user-home/`）。
- **G2.** 存活语义：`/mnt/user-home/` 里的文件要跨线程清理、跨沙箱容器重启、跨 Gateway 重启都活着。
- **G3.** 向后兼容：现有 `/mnt/user-data/...` 行为完全不变，新挂载是纯增量。
- **G4.** 沙箱安全模型保持：挂载仍然按 `user_id` 隔离，跨用户泄露仍然不可能。
- **G5.** 改动最小：只动 config + sandbox + middleware + tools + 一处 prompt + 两个文档。不改 `ThreadState` 语义、不改 `memory.json` schema、不要求用户改配置。

### 非目标

- **NG1.** 不替换 `/mnt/user-data/...`——线程隔离保留。
- **NG2.** 不改 per-user `skills/` 挂载语义——skills 仍只读。
- **NG3.** 不引入新数据库表——纯文件系统。
- **NG4.** 不解决上游 #1978 的 PVC / `hostPath` 之争——本设计只挑 hostPath 布局；PVC 后续再说。
- **NG5.** 不引入跨主机同步——多机部署时 NFS 行为由运维负责。

---

## 方案选型

### 方案 A（采纳）：单一扁平目录 `/mnt/user-home/`

```
backend/.deer-flow/users/{user_id}/home/  →  /mnt/user-home/  (rw)
```

- 优点：模型最简单，一个挂载、一条路径规则、没有嵌套结构决策。"文件丢这里"的直觉心智模型——Obsidian vault、装的 CLI、`projects/` 子目录统统并列。
- 缺点：长期可能成"杂物抽屉"，没有"工具 vs 数据"的天然分隔。

### 方案 B（否决）：Linux `$HOME` 风格（XDG 目录）

```
backend/.deer-flow/users/{user_id}/home/  →  /mnt/user-home/  (rw, 容器的 $HOME)
├── .config/    →  /mnt/user-home/.config/    (XDG_CONFIG_HOME)
├── .local/     →  /mnt/user-home/.local/     (XDG_DATA_HOME / XDG_BIN_HOME)
└── .cache/     →  /mnt/user-home/.cache/     (XDG_CACHE_HOME)
```

- 优点：Unix 标准；很多 CLI（rustup、`pip --user`、npm `--prefix`）不需要环境变量技巧；工具/数据自动分流；将来可按类目加 size 限制。
- 缺点：隐藏目录让不熟 XDG 的 agent 困惑；沙箱里 `$HOME` 重布线成本不低；Obsidian vault 在 XDG 之外；现有 skill 大多要改。

### 方案 C（否决）：扁平 + `$HOME` 软链

```
/mnt/user-home/  (扁平, rw)
├── vault/
├── bin/notesmd-cli
└── projects/
$HOME  →  /mnt/user-home/   (symlink 或 env var)
```

- 优点：agent 用简单路径，读 `$HOME` 的 Unix 工具也透明。两全其美。
- 缺点：接线多（沙箱环境变量注入、Docker bind-mount 语义小心）；两套范式共存会让模型对"文件住哪"产生推理混乱。

### 选择方案 A 的理由

- 用户主诉的用例（Obsidian vault + 装 CLI）正好是"文件丢这里"模式。
- 上游现有的 `/mnt/skills` 挂载就是扁平的，沿用同样约定降低认知负担。
- YAGNI：XDG 结构是 v2 问题，等真有 Unix 工具需要再上。
- 方案 C 太巧——以后可以加 `$HOME` symlink 作为非破坏性增强，不需要现在一起做。

---

## 架构

```
┌──────────────────────────────────────────────────────────┐
│ Host filesystem                                          │
│                                                          │
│ backend/.deer-flow/users/{user_id}/                      │
│ ├── home/                    ← 新增：每用户持久化家目录  │
│ │   ├── vault/                  惰性 mkdir on 首次访问   │
│ │   ├── bin/                    chmod 0o777              │
│ │   └── notes.md                                            │
│ ├── threads/{thread_id}/                                │
│ │   └── user-data/             现有：每线程临时           │
│ │       ├── workspace/                                       │
│ │       ├── uploads/                                         │
│ │       └── outputs/                                         │
│ ├── memory.json               现有：每用户元数据          │
│ └── agents/{agent_name}/      现有：每用户自定义 agent   │
└────────────────┬─────────────────────────────────────────┘
                 │ bind mount (rw, single user)
                 ▼
┌──────────────────────────────────────────────────────────┐
│ Sandbox container                                        │
│                                                          │
│ /mnt/user-home/*        ← 新增：跨线程可写                │
│ /mnt/user-data/*        ← 现有：每线程临时（不动）        │
│ /mnt/skills/*           ← 现有：每用户只读（不动）        │
│ /mnt/acp-workspace/*    ← 现有：每线程只读（不动）        │
└──────────────────────────────────────────────────────────┘
```

---

## 设计细节

### 路径布局

| 虚拟路径 | 作用域 | 生命周期 | 模式 |
|----------|--------|----------|------|
| `/mnt/user-data/{workspace,uploads,outputs}` | 每线程 | 线程 | rw（现有） |
| `/mnt/skills/{public,custom}` | 每宿主机 | 宿主机 | ro（现有） |
| `/mnt/acp-workspace/*` | 每线程 | 线程 | ro（现有） |
| **`/mnt/user-home/*`** | **每用户** | **用户** | **rw（新增）** |
| 自定义挂载（config.yaml） | 配置决定 | 配置决定 | 配置决定 |

### 配置

在 `config.example.yaml` 新增（默认开启，向后兼容）：

```yaml
sandbox:
  user_home:
    enabled: true                  # 总开关；false 时挂载跳过、提示词不提及
    container_path: /mnt/user-home # 沙箱内挂载点；保留可改以便将来重命名
```

Pydantic 模型：`SandboxUserHomeConfig { enabled: bool = True; container_path: str = "/mnt/user-home" }`，挂到现有 `AppConfig.sandbox` 下。

### 改动文件清单

| 文件 | 变更 |
|------|------|
| `backend/packages/harness/deerflow/config/paths.py` | 新增 `user_home_dir(user_id) -> Path` 和 `host_user_home_dir(user_id) -> Path`。首次调用 `mkdir(parents=True, exist_ok=True, mode=0o777)`，与现有 `workspace_dir()` 一致。 |
| `backend/packages/harness/deerflow/config/skills_config.py`（或 `sandbox_config.py`） | 新增 `SandboxUserHomeConfig`，挂到 `AppConfig.sandbox.user_home`。 |
| `backend/packages/harness/deerflow/agents/thread_state.py:10-13` | `ThreadDataState` TypedDict 新增两个字段：`user_home_path: NotRequired[str \| None]`（宿主机路径）和 `user_home_container_path: NotRequired[str \| None]`（沙箱内挂载点，默认 `/mnt/user-home`）。 |
| `backend/packages/harness/deerflow/agents/middlewares/thread_data_middleware.py` | 在 `before_agent` 注入 `user_home_path`（宿主机路径）和 `user_home_container_path`（沙箱内挂载点）。`user_id` 通过现有 `get_effective_user_id()` 解析（**不要**从 `workspace_path` 反推 —— 见 R5）。 |
| `backend/packages/harness/deerflow/sandbox/local/local_sandbox_provider.py` | `_build_thread_path_mappings`：当 `user_home.enabled=true` 且 `host_user_home_dir(user_id).exists()` 时，新增映射 `(host_dir, container_path, read_only=False)`。目录缺失时静默跳过（降级模式）。 |
| `backend/packages/harness/deerflow/sandbox/tools.py` — `_thread_virtual_to_actual_mappings`（line ~522） | 在 `replace_virtual_path` 用的 `(virtual_prefix, host_path)` 列表里加入 `("/mnt/user-home", thread_data["user_home_path"])`，按 `len` 降序排序保持与现有 skills/workspace 一致。 |
| `backend/packages/harness/deerflow/sandbox/tools.py` — `_validate_resolved_user_data_path`（line ~689） | `allowed_roots` 列表加入 `Path(thread_data["user_home_path"]).resolve()`，与现有 `workspace_path`/`uploads_path`/`outputs_path` 对称。 |
| `backend/packages/harness/deerflow/sandbox/tools.py` — `replace_virtual_paths_in_command`（line ~999/1010/1021） | 新增 `/mnt/user-home` 虚拟前缀扫描；**注意**现有 regex `(/[^\s\"';&|<>()]*)?` 在 `heredoc`/quoted string 内遇到带空格的路径会被截断，user-home 同款风险需要在 prompt 和 doc 显式提示（推荐 skill 作者用 quoted path 或避免空格）。 |
| `backend/packages/harness/deerflow/sandbox/tools.py` | 新增 `_is_user_home_path(path)` / `_resolve_user_home_path(path, user_id)`（与 `_is_skills_path` 对称）。扩展 `validate_local_tool_path`、`replace_virtual_path`、`_is_allowed_local_bash_absolute_path` 三个函数识别 `/mnt/user-home/*`。**注意**：host 路径含 `user_id`，与 skills 单例缓存不兼容，每次按 user_id 重算 host path，不要缓存。 |
| `backend/packages/harness/deerflow/community/aio_sandbox/local_backend.py` | 在 `create()` 和 `_start_container()` 的 `extra_mounts` 列表里新增 `(host_user_home_dir(uid), container_path, read_only=False)`。 |
| `backend/packages/harness/deerflow/community/aio_sandbox/remote_backend.py:135-146` | **R-Remote-Mount 缺口**：当前 `_provisioner_create` 的 POST payload 只含 `sandbox_id`/`thread_id`/`user_id`，**`extra_mounts` 参数被静默丢弃**。Phase 1 必须在远端模式加 startup warning：检测 `sandbox.user_home.enabled=true` 且当前 backend 是远端 provisioning 时，启动时 `logger.error` 并在 `config.example.yaml` 注明"远端模式待 Phase 2 修复"。具体修复（payload 加 `mounts` 字段并要求 provisioner 端支持）出本设计范围。 |
| `backend/packages/harness/deerflow/agents/lead_agent/prompt.py` | 新增系统提示（紧跟现有 skills 段后面）："Persistent user home: `/mnt/user-home/` (rw, survives across threads; use for files the user wants to keep). Note: structured facts/memories are still extracted into `memory.json`/`USER.md` automatically — `/mnt/user-home/` is for raw files only." 仅当 `enabled=true` 时注入。 |
| `config.example.yaml` | 上述 `sandbox.user_home` 配置块。bump `config_version`。changelog 加一条"v13 引入 `sandbox.user_home`（默认 enabled），老用户首次升级时 `/mnt/user-home/` 会自动挂载"。 |
| `backend/CLAUDE.md` + 根 `CLAUDE.md` | 在"沙箱系统"段补一段：新增 `/mnt/user-home/` 虚拟路径。 |

### 数据流

**跨会话写入**：

```
会话 N：
  agent → write_file("/mnt/user-home/notes.md", "...")
    ↓
  sandbox/tools.py:validate_local_tool_path(path, thread_data, read_only=False)
    ↓ _is_user_home_path 命中，read_only=False → 通过
  replace_virtual_path("/mnt/user-home/notes.md", thread_data)
    ↓ 命中 user_home_path 前缀
  → backend/.deer-flow/users/{user_id}/home/notes.md
    ↓
  原子写入，权限 0o777

会话 N+1：
  ThreadDataMiddleware.before_agent()
    ↓ get_effective_user_id() 从 JWT 解析
    ↓ thread_data["user_home_path"] = host_user_home_dir(user_id)
  LocalSandboxProvider.acquire(thread_id)
    ↓ _build_thread_path_mappings 包含 (host_dir, "/mnt/user-home", rw)
  agent 读 /mnt/user-home/notes.md → 看到会话 N 的内容
```

**生命周期**：

- `home/` 惰性 `mkdir`——首次通过 `user_home_dir()` 访问时创建（与现有 `workspace_dir()` 行为一致）
- `delete_thread_dir(thread_id)` **不**触碰 `home/`（已有代码改 `threads/{tid}` 整棵树，**需要确认并测试**它不会越界扫到 `home/`）
- 新增 `delete_user_dir(user_id)` 方法——显式运维清理（GDPR 路径），本次**不**通过 HTTP 暴露

### Subagent 隔离

**结论：subagent 隔离对 user-home 是零成本透明的，不需要额外挂载。**

依据：`backend/packages/harness/deerflow/subagents/executor.py:478-479` 的 `SubagentExecutor._build_initial_state` 把 `thread_data` 直接透传给子图：

```python
if self.thread_data is not None:
    state["thread_data"] = self.thread_data
```

子图（subagent）跑在**同一个 sandbox**——`task()` 工具不创建新 container，subagent 通过 background thread 共享 lead agent 的 sandbox client（详见 `SubagentLimitMiddleware` 和 executor 实现）。这意味着：

- 子图的 `thread_data["user_home_path"]` 自动继承 lead agent 的 host 路径；
- 沙箱内 `/mnt/user-home/` 在 subagent 视角下已经挂载（local provider 走的同一份 `PathMapping`）；
- AIO 后端同样：subagent 不创建新 container → 同一挂载可见。

**实现要求**：

- 不要在 `SubagentExecutor` 里加任何 user-home 相关代码；
- `ThreadDataState` 字段扩展后，subagent 的 `before_agent` 链自然继承，无需注入；
- 测试覆盖：写一个 subagent 在 `home/` 里写文件、subagent 完成后 lead agent 读出来的端到端测试（验证透传链没断）；
- **不要**给 subagent 单独的 sandbox mount——会破坏 subagent 与 lead agent 的 `home/` 共享语义。

**潜在陷阱**：

- `MAX_CONCURRENT_SUBAGENTS = 3` 下，三个 subagent 并发写同一 `home/` 子路径的并发安全与 lead agent 写自己的 `home/` 共享同一约束（见 R3）；
- subagent 调用的工具如果走 `present_files` 工具（`backend/packages/harness/deerflow/tools/builtins/present_file_tool.py:13` 硬编码 `OUTPUTS_VIRTUAL_PREFIX = f"{VIRTUAL_PATH_PREFIX}/outputs"`），**不能**展示 `/mnt/user-home/*`——这是设计内决策（见成功标准 #5），不需要扩展 present_file。

### 错误处理与安全

| 场景 | 行为 |
|------|------|
| `user_home.enabled = false` | 挂载跳过；系统提示里也不提；完全向后兼容。 |
| 宿主机 `home/` 不存在（未访问过） | 静默跳过挂载（降级模式，类比 `workspace/` 缺失）。 |
| 路径穿越 `/mnt/user-home/../etc` | `_reject_path_traversal` → `PermissionError`（已实现）。 |
| 跨用户访问 | 构造上不可能：`replace_virtual_path` 在沙箱获取时就锁定了 user_id，不从路径字符串里取。 |
| 权限漂移 | 沿用 `user-data` 的 `0o777` 模式（有现成测试覆盖）。 |
| 磁盘占满 | 不在范围；写入失败由现有错误处理链捕获。文档化为已知风险。 |
| AIO 远端模式 | `extra_mounts` payload 通过 `remote_backend.py` 透传；远端 provisioning 需要识别 `rw=false` 表示可写（`#2486` 已支持）。 |
| 并发写 | 同一 `home/` 子目录的并发写没有显式锁；依赖文件系统原子 rename。与现有 `workspace/` 行为一致。 |

### 权限模型

`/mnt/user-home/` 继承 `/mnt/user-data/` 的权限方案：`mkdir(..., mode=0o777)` 让沙箱容器（可能是不同 UID）可写。沙箱用户可自由读写；宿主机可自由读写。

### 测试

| 测试文件 | 类型 | 覆盖点 |
|----------|------|--------|
| `tests/test_user_home_dir.py`（新增） | 单元 | `paths.user_home_dir()` / `host_user_home_dir()` 辅助函数；首次调用 mkdir；mode 0o777；同一 user 多次调用幂等；不同 user 拿到不同路径 |
| `tests/test_sandbox_tools_security.py`（扩展） | 单元 | `/mnt/user-home/x` 通过 `validate_local_tool_path`；穿越 `..` 被拒；`write_file` 允许；`str_replace` 允许；`read_only=True` 也允许（与 skills 一致——读总允许） |
| `tests/test_local_sandbox_virtual_path_contract.py`（扩展） | 单元 | `_build_thread_path_mappings` 在 `enabled=true` 时包含 user-home 映射；`enabled=false` 时不含；`home/` 缺失时降级跳过 |
| `tests/test_local_sandbox_virtual_path_contract.py`（新增段） | 单元 | 跨用户隔离：User A 的 `/mnt/user-home/` 不指向 User B 的 `home/`；两个 user 各自的挂载独立 |
| `tests/test_thread_data_middleware.py`（扩展） | 单元 | `user_home_path` / `user_home_container_path` 正确注入；与 `get_effective_user_id()` 衔接；no-auth 模式 fallback 到 `"default"` |
| `tests/test_aio_user_home_mount.py`（新增） | 单元 | AIO `extra_mounts` payload 在 `enabled=true` 时包含 `(host_dir, "/mnt/user-home", read_only=False)`；远端 payload 透传该字段 |
| `tests/test_delete_thread_dir_isolation.py`（新增） | 单元 | `delete_thread_dir(thread_id)` 只删 `threads/{tid}/`，**不**删兄弟目录 `home/` |
| `tests/test_skills_prompt_section.py` 或 `tests/test_lead_agent_skills.py`（扩展） | 单元 | `enabled=true` 时系统提示包含 "Persistent user home" 段；`enabled=false` 时不包含 |

### 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| 磁盘占满（R1） | 宿主磁盘被用户填满 | 文档化已知风险；后续加 size 限制（出本设计范围） |
| 沙箱权限漂移（R2） | host/container UID 不一致 | 沿用 `0o777` 模式；新测试覆盖 |
| agent 跨挂载推理混乱（R3） | 把临时文件写到 `/mnt/user-home/`、或把事实写到 home 而不是 memory.json | 系统提示明确语义；区分"thread 临时（user-data）"、"user 持久（user-home）"、"事实提取（memory.json/USER.md）"三类路径 |
| 破坏 skill 契约（R4） | skill 改了行为 | 纯增量；不需要改 skill；后续可选给当前复制到 workspace 的 skill 加 user-home 副本 |
| AIO 远端 provisioning 静默丢失 `extra_mounts`（R5，**已核实**：原风险表第 5 行描述错误） | `remote_backend.py:135-146` 的 `_provisioner_create` POST payload **不含** `extra_mounts` 字段——参数被静默丢弃；远端 provisioning 模式下 `/mnt/user-home/` 完全不挂载 | **Phase 1 缓解**：启动时检测 `sandbox.user_home.enabled=true` 且 backend 是 remote provisioning，`logger.error` 输出 actionable warning；`config.example.yaml` 注明"远端模式待 Phase 2 修复"。**完整修复**（payload 加 `mounts` 字段、要求 provisioner 端支持）出本设计范围 |
| `delete_thread_dir` 误删 `home/`（R6） | 数据丢失 | 新测试 `test_delete_thread_dir_isolation.py` 显式断言兄弟目录 `home/`/`memory.json`/`agents/` 不被删；当前 `paths.py:337-344` 实现是 `shutil.rmtree(thread_dir)` 单目录删，**理论上安全**，但需要测试锁定 |
| host 路径含 `user_id` 与 skills 单例缓存不兼容（R7，**新发现**） | skills 走 `_get_skills_host_path` 进程级单例缓存（`tools.py:120`），host 路径不含 user_id；user-home 的 host 路径**含** user_id——沿用同一缓存模式会跨用户错位 | user-home 的 `_resolve_user_home_path` 每次按 `get_effective_user_id()` 重算 host path，**不要缓存**。新测试覆盖：User A 调用后 User B 调用拿到不同路径 |
| `replace_virtual_paths_in_command` regex 在 quoted string/heredoc 内遇空格截断（R8，**新发现**） | `/mnt/user-home/My\ Notes/file.md` 或 heredoc 内引用带空格路径时被截到第一个空格，写到错位置或 PermissionError | prompt 提示 skill 作者用 quoted path 或避免空格；不在 Phase 1 修 regex（`tools.py:999/1010/1021` 已有 4 处 regex，跨多函数，单独评估） |

---

## 不在范围（推迟）

- `$HOME` 重定向（YAGNI；v2 可作非破坏性增强）
- USER.md / agents/ 合并（保持独立；归类清晰）
- 配额 / size 限制
- PVC / 分布式存储（上游 #1978）
- 跨主机同步
- 备份集成
- `delete_user_dir()` 通过 HTTP 暴露

---

## 成功标准

1. 用户在会话 N 写入 `/mnt/user-home/vault/notes.md`，在会话 N+1 仍可读到。
2. 用户安装 CLI 二进制到 `/mnt/user-home/bin/foo`，下次会话仍可执行。
3. 新线程的 `home/` 自动创建并挂载，无需手动配置。
4. `delete_thread_dir(thread_id)` **不**触碰 `home/`。
5. 两个用户在同一 `thread_id`（实际不可能，但需测试）拿到各自隔离的 `home/`。
6. 所有现有测试通过；新测试覆盖路径校验、ACL、跨用户隔离、降级模式。
7. AIO 远端 provisioning 模式下有显式行为声明：`sandbox.user_home.enabled=true` 且 backend 是 remote provisioning 时启动输出 actionable warning；本地 `config.example.yaml` 注明"远端挂载待 Phase 2 修复"。

---

## 后续 Phase 计划

- **Phase 2（可选）**：加 `$HOME=/mnt/user-home` 软链，激活 Unix 工具原生 `$HOME` 行为
- **Phase 3（可选）**：升级到 XDG 风格（`.config/.local/.cache`）
- **Phase 4（可选）**：配额 / size 限制
- **Phase 5**：对接上游 PVC 存储（#1978）

---

## OpenSpec 对接

按本仓库 `CLAUDE.md` 的 OpenSpec 流程，本设计对应：

- `proposal.md`：背景、目标、非目标、问题陈述（即本文"背景与目标"段）
- `design.md`：方案选型、架构、改动清单、风险（即本文主体）
- `tasks.md`：实现步骤（即下一步 writing-plans 的输出）

tasks.md 将基于本文"改动文件清单"和"测试"两段展开为可勾选清单。