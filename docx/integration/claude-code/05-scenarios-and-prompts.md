# `claude_code` 子代理 —— 适用场景、提示词模板与跟现有 subagent 的边界

> 配套文档：[`03-integration-design.md`](03-integration-design.md) · [`04-open-decisions.md`](04-open-decisions.md)
> 来源：基于 DeerFlow 现有 `subagents/builtins/{general_purpose,bash_agent}.py` 模式 + Claude Code CLI 设计目标 + 决策 0 发现的 mode 约束
> 日期：2026/06/06

## 一、4 种 mode × 3 类子代理的可用矩阵

| Mode | general-purpose（已有） | bash（已有） | **claude_code（待加）** | 说明 |
|---|---|---|---|---|
| `flash`（闪速） | ❌ | ❌ | ❌ | 整个 subagent 系统关掉 |
| `thinking` | ❌ | ❌ | ❌ | subagent_enabled = false |
| `pro` | ❌ | ❌ | ❌ | subagent_enabled = false |
| `ultra` | ✅ | ✅ | ✅ | 唯一能调 subagent 的 mode |

> **结论**：`claude_code` 子代理**只在 ultra 模式**下能被 lead agent 选用。这是一个"硬开关"，不是软建议。

---

## 二、`claude_code` vs `general-purpose` vs `bash` —— 怎么分工？

> 类比：lead agent 像项目经理，把活分给三类"员工"。

| 维度 | `general-purpose` | `bash` | `claude_code`（新） |
|---|---|---|---|
| **专长** | 通用多步任务 | 跑 bash 命令 | **编码 / 重构 / 调试 / 跑测试** |
| **工具集** | 继承 lead agent 的全部工具（除了 `task` / `ask_clarification` / `present_files`） | 仅沙箱工具（bash / ls / read_file / write_file / str_replace） | SDK 内置（Read/Edit/Write/Bash/Grep/Glob/NotebookEdit/WebFetch/WebSearch）+ DeerFlow 沙箱工具通过 in-process MCP 喂入 |
| **系统提示词来源** | 静态写在 `general_purpose.py` | 静态写在 `bash_agent.py` | SDK 默认 `claude_code` preset + DeerFlow append 段 |
| **模型** | `inherit`（跟随 lead agent） | `inherit` | **DeerFlow 配什么 Claude 模型，SDK 就用同一个**（建议从 `app_config.models` 解析） |
| **典型工作时长** | 中（一般任务） | 短（命令集合） | **长**（跨多文件、跑测试循环、debug） |
| **返回值给 lead agent** | 一段文字总结 | 命令输出摘要 | **结构化产出**（修改了哪些文件、跑了什么命令、测试结果） |
| **用户能"看到"它干活吗** | 能（前端流） | 能 | **更能**（`include_partial_messages=True` 实时显示思考 + 工具调用 + 输出） |
| **lead agent 啥时候选它** | 默认多步委派 | 跑命令系列 | 复杂编码 / 重构 / debug |

### Lead agent 的"决策树"（系统提示里给它的建议）

```
用户问 → lead agent 想：这事要不要委派给子代理？
         │
         ├─ 是简单的单命令（"ls 一下"）→ 直接用 bash 工具
         │
         ├─ 是命令集合（"跑 build + 跑 test + 看 log"）→ task(subagent_type="bash")
         │
         ├─ 是编码 / 重构 / 调试 / 测试
         │  ├─ 简单（改一两行）→ 直接用 Edit/Write 工具
         │  └─ 复杂（跨多文件、可能要查 git、跑 build、debug）→ task(subagent_type="claude_code")
         │
         └─ 是其他多步任务（研究、写报告、调 API）→ task(subagent_type="general-purpose")
```

> 这套决策树**写在 lead agent 的系统提示词里**（`_build_subagent_section` 那段）。PR #2 要在那一段里加 `claude_code` 的描述 + 啥时候用。

---

## 三、`claude_code` 子代理的典型使用场景

### ✅ 适合用 `claude_code` 的场景

| 场景 | 例子 |
|---|---|
| **跨多文件重构** | "把 `auth/` 目录下所有用 MD5 哈希的地方换成 bcrypt" |
| **功能开发** | "在 `chat/` 加一个 streaming 模式，UI 上加个开关" |
| **Bug 调试** | "登录接口偶发 500，看下日志定位到具体函数" |
| **测试编写** | "给 `payment/processor.py` 写 pytest 单元测试，覆盖边界情况" |
| **依赖升级** | "把 React 18 升到 19，跑 build 修 breaking change" |
| **Code review 后整改** | "按这个 PR 的 review 意见改：a.py 的循环复杂度、b.py 的命名" |
| **CI / 构建脚本** | "写个 GitHub Action 跑 lint + test + 自动开 issue" |
| **数据库迁移脚本** | "写个 alembic 迁移，给 `orders` 表加 `discount` 列；写回填 SQL" |

### ❌ **不**适合用 `claude_code` 的场景

| 场景 | 改用 |
|---|---|
| 写完代码要跑长任务、还要把过程展示给用户 | lead agent 自己干（保留 streaming 上下文） |
| 简单一句话单命令（"ls 一下"） | `bash` 工具 |
| 写论文 / 翻译 / 写报告 / 数据分析 | `general-purpose` |
| 调外部 API（不是改代码） | `general-purpose` |
| 用户想看到 lead agent 自己一步步思考 | **别**委派 |

---

## 四、提示词长什么样？

### 4.1 用户视角：写给 lead agent 的自然语言任务

用户**不需要**给 claude_code 写专门提示词。用户的提示词还是给 lead agent 的自然语言：

```
帮我把 src/auth/ 下面所有用 MD5 哈希的地方换成 bcrypt。
要求：
1. 保持现有 API 兼容
2. 跑现有测试，确保不挂
3. 写个 migration 记录这次升级
```

Lead agent 在 ultra 模式下看到这个任务，**自己决定**要 `task(subagent_type="claude_code", prompt=...)`，把上述任务 + 它觉得需要的额外上下文（"这是 Python 3.12 项目，用 FastAPI，DB 是 PostgreSQL..."）打包传给子代理。

### 4.2 lead agent 视角：传给 `claude_code` 的 prompt

**这部分由 lead agent 写**——我们没法强制它怎么写，但可以在它的系统提示里"训"它。下面是给 lead agent 的 prompt 模板建议（写到 `agents/lead_agent/prompt.py`）：

```python
# Lead agent 系统提示里关于 claude_code 子代理的说明段（建议）
"""
When you delegate coding/refactoring/debugging tasks to the `claude_code` subagent,
construct the prompt with this structure:

1. **Task summary** (1-2 sentences): what to do
2. **Context** (only what Claude Code can't infer):
   - Tech stack & versions
   - Project conventions
   - Test framework
3. **Acceptance criteria** (concrete):
   - Files to modify (or "you decide")
   - Commands to run (build / lint / test)
   - Expected output (test pass / no errors)
4. **Constraints**:
   - Don't touch unrelated files
   - Keep API backwards-compatible (unless told otherwise)
   - Use existing patterns, don't invent new abstractions
5. **Return format**:
   - Files changed (with paths)
   - Tests run (with results)
   - Any decisions you made and why

Example:
---
Task: Replace all MD5 hashes in src/auth/ with bcrypt while keeping API stable.
Context: Python 3.12, FastAPI, SQLAlchemy, existing test suite in tests/test_auth.py.
Acceptance: All existing tests pass; new bcrypt helper is in src/auth/hash.py.
Constraints: Don't change public function signatures; keep deprecation warnings.
Return: list of changed files, test output, any compatibility decisions.
---
"""
```

### 4.3 `claude_code` 子代理自己的系统提示（DeerFlow 端配置）

**这部分由 DeerFlow 配**（写到 `subagents/builtins/claude_code_agent.py` + ClaudeAgentOptions.system_prompt.append）。建议结构：

```python
CLAUDE_CODE_CONFIG = SubagentConfig(
    name="claude_code",
    description=(
        "Anthropic's Claude Code coding agent, backed by the official "
        "claude-agent-sdk. Specialized for multi-file code edits, refactoring, "
        "debugging, test writing, and build/dependency tasks. Uses the SDK's "
        "built-in file tools (Read/Edit/Write) plus DeerFlow sandbox tools "
        "via mcp__deerflow__* prefix. Use this when the task involves modifying "
        "code across multiple files, running tests, or doing iterative "
        "build-fix cycles. Not for simple one-line edits — use the Edit tool "
        "directly for that. Not for non-coding research/writing — use "
        "general-purpose for that."
    ),
    system_prompt="""\
You are the Claude Code subagent of a DeerFlow lead agent. The lead agent has
delegated a coding task to you because it requires focused, multi-step
engineering work.

## Your environment
- Working directory: per-thread workspace at /mnt/user-data/workspace/
- User uploads available: /mnt/user-data/uploads/
- Outputs go to: /mnt/user-data/outputs/
- DeerFlow sandbox tools available via `mcp__deerflow__*` prefix:
  - mcp__deerflow__bash       — run shell commands (use this for build/test/install)
  - mcp__deerflow__read_file  — read file
  - mcp__deerflow__write_file — write file
  - mcp__deerflow__str_replace — in-place string edit
  - mcp__deerflow__ls         — list directory

## Your deliverables
- **Modify files** using SDK's Read/Edit/Write tools (preferred) or
  `mcp__deerflow__write_file` / `mcp__deerflow__str_replace` if you need
  DeerFlow-side audit logging.
- **Run build/test/lint** via `mcp__deerflow__bash`. Always run the project's
  test suite after non-trivial changes and report results.
- **Final answer** should include:
  1. Files changed (paths, line counts)
  2. Commands run with outcomes
  3. Test results (pass/fail counts)
  4. Decisions / trade-offs you made
  5. Open questions (if any)

## Working style
- Make the smallest set of changes that solves the task
- Don't refactor unrelated code
- If you hit ambiguity, pick the most likely interpretation and document it
- Don't add features the lead agent didn't ask for
""",
    tools=None,  # SDK handles file tools; we just expose DeerFlow sandbox via MCP
    disallowed_tools=["task", "ask_clarification", "present_files", "invoke_acp_agent"],
    model="inherit",  # or specific Claude model from config
    max_turns=80,
    timeout_seconds=1200,  # 20 min — coding tasks often need more than 15 min
)
```

### 4.4 Lead agent 给 `claude_code` 的 prompt 范例（实际跑起来时）

**用户的原始问题**：

```
帮我把 src/auth/ 下面所有用 MD5 哈希的地方换成 bcrypt。
要求：
1. 保持现有 API 兼容
2. 跑现有测试，确保不挂
3. 写个 migration 记录这次升级
```

**Lead agent 在 ultra 模式下的内部决策**（伪代码）：

```python
# lead agent 决定委派
task(
    subagent_type="claude_code",
    description="Replace MD5 with bcrypt in src/auth/",
    prompt="""
## Task
Replace all MD5 hash usage in `src/auth/` with bcrypt while keeping the public
API of `auth.password` module unchanged. Run existing tests, add a migration
note.

## Context
- Python 3.12 / FastAPI / SQLAlchemy 2.0
- Existing tests: `pytest tests/test_auth.py` (currently 47 passing)
- Project convention: hash utilities live in `src/auth/hash.py`; we already
  have `passlib[bcrypt]==1.7.4` in requirements.txt
- DB column is `password_hash VARCHAR(255)`, currently stores MD5 hex (32 chars);
  bcrypt produces 60-char strings — column already wide enough

## Acceptance
- `src/auth/hash.py` exposes `hash_password(plain) -> str` and
  `verify_password(plain, hashed) -> bool`. `hash_password` switches to bcrypt
- All callers of legacy `md5_hash` function in `src/auth/` either:
  (a) updated to use `hash_password`, or
  (b) keep a deprecation shim that hashes with bcrypt on next login
- `pytest tests/test_auth.py` passes
- A markdown note `docs/migrations/2026-06-06-md5-to-bcrypt.md` explains
  rollout (re-hash on next login; no backfill needed)

## Constraints
- Don't change the function signature of any function imported outside `src/auth/`
- Keep backward compatibility: existing MD5-hashed passwords in DB must still
  verify successfully (use the "rehash on login" pattern)
- Don't add new dependencies (bcrypt is already in requirements.txt)
- Don't refactor unrelated auth code (sessions, JWT, etc.)

## Return format
- List of files changed (with line counts)
- `pytest` output (final line should be "47 passed" or similar)
- The migration note path
- One paragraph: any decisions / trade-offs you made
""",
)
```

---

## 五、`claude_code` 子代理**不**应该被调用的场景（lead agent 提示词里要"训"它）

| 反模式 | 为什么不好 | 改用 |
|---|---|---|
| 跑**只读**信息搜集（"看看 X 项目怎么做的"） | 浪费 SDK 的写权限；可能误改文件 | `general-purpose` 或 lead agent 自己干 |
| 处理**非编码**任务（写报告、分析数据、调 API） | Claude Code 的工具集是为编码优化 | `general-purpose` |
| 用户在**闪速/思考/Pro 模式**下 | mode 本身就关掉了 subagent_enabled | （不调用） |
| 委派**之后再让子代理委派**（嵌套子代理） | 已通过 `disallowed_tools=["task"]` 屏蔽 | （不会发生） |
| 子代理让 lead agent 来澄清 | 已通过 `disallowed_tools=["ask_clarification"]` 屏蔽 | （不会发生） |

---

## 六、给 lead agent 的"调度建议"提示词段（直接 copy 进 `_build_subagent_section`）

```python
# agents/lead_agent/prompt.py:_build_subagent_section 里加的子代理描述（建议）
SUBAGENT_DESCRIPTIONS = {
    "general-purpose": (
        "For complex multi-step tasks that need exploration + action "
        "(research, writing, API calls, data analysis). NOT for simple "
        "single-step operations."
    ),
    "bash": (
        "For executing a series of related shell commands (build, test, "
        "deploy). Use the bash tool directly for one-off commands."
    ),
    "claude_code": (  # 新增
        "Anthropic's Claude Code agent for multi-file code edits, "
        "refactoring, debugging, writing tests, and build/dependency tasks. "
        "Backed by the official claude-agent-sdk with Read/Edit/Write/Bash/"
        "Grep/Glob tools plus DeerFlow sandbox tools via mcp__deerflow__*. "
        "Use for tasks that touch multiple files, need iterative "
        "build-fix cycles, or require test execution. NOT for simple one-"
        "line edits (use the Edit tool directly) or non-coding research "
        "(use general-purpose)."
    ),
}
```

---

## 七、检查清单（PR #2 落地时按这个核对）

- [ ] `claude_code` 子代理**只在 ultra 模式**通过 `_build_subagent_section` 注入到 lead agent 系统提示
- [ ] `claude_code` 的 `disallowed_tools` 至少包含：`task`、`ask_clarification`、`present_files`、`invoke_acp_agent`
- [ ] `claude_code` 的 `system_prompt` 包含"工作目录在哪 / 沙箱工具前缀是什么 / 返回值要包含什么"
- [ ] `claude_code` 的 `max_turns ≥ 60`、`timeout_seconds ≥ 1200`（编码任务比一般任务长）
- [ ] `claude_code` 的 `model` 配置：默认 `inherit`，可被 `subagents_config.agents.claude_code.model` 覆盖
- [ ] 集成测试覆盖：ultra 模式 → lead agent 委派 → claude_code 跑通；flash 模式 → `task` 工具不存在
- [ ] 集成测试覆盖：claude_code 子代理尝试调 `task` / `ask_clarification` / `invoke_acp_agent` → 被拒
- [ ] 前端 `InputBox` 的 mode 选择器默认选 pro（不改）；用户主动切到 ultra 才能用 claude_code
