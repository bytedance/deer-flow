# DeerFlow Coding Agent

基于 [DeerFlow](https://github.com/bytedance/deer-flow) 二次开发的可恢复多 Agent Coding Agent。

它面向真实 Git 仓库执行分析、审查和编码任务：先由人工确认计划，再创建持久化任务 DAG 和独立 Git Worktree；用户可选择只分析、只审查，或依次委派代码分析、实现与审查 Agent，最后根据测试证据和审查报告给出结果。

> 本项目保留 DeerFlow 2.0 的 Agent Harness、MCP、Skill、Sandbox、Checkpoint 和 Web UI，并在其上增加 Coding 场景的任务控制层与隔离执行链。

## 核心能力

- **GitHub Issue MCP**：通过自定义 MCP Server 读取 Issue，整理为结构化 `coding_brief`。
- **Coding Skill**：按用户意图选择只分析、只审查或分析→实现→审查流程，并固定输入门禁、人工审批、失败处理和输出契约。
- **三角色 Sub-Agent**：`code-analyzer`、`code-implementer`、`code-reviewer` 是源码内置角色，分别拥有只读分析、读写实现、只读审查工具边界。
- **结构化 Agent 交接**：三类报告由 Pydantic 校验并持久化，下游任务从 DAG 自动取得已验证的上游产物，不依赖 Lead Agent 手工复制文本。
- **持久化目标与 Task DAG**：将用户确认的 `coding_brief` 保存为线程级目标契约，并保存任务依赖、指定角色、领取者、执行状态、结构化产物、失败原因和 Worktree；子 Agent 新建上下文时会重新注入目标，支持进程重启后恢复。
- **Git Worktree 隔离**：在用户选择的本地 Git 仓库中创建独立目录和分支，避免 Agent 修改污染主工作区。
- **Human-in-the-loop**：执行计划、技术失败重试，以及审查 FAIL 后的重新分析→修复→复审都需要匹配当前请求的结构化人工确认。
- **生产运行时接线**：Coding 工具接入 Gateway 的真实工具装配路径，外部 Worktree 可安全传递到子 Agent 中间件与文件工具。

## 工作流程

```text
GitHub Issue / coding_brief
  -> multi-agent-coding Skill + 人工批准
  -> workflow_type 选择 analyze_only / review_only / implement_and_review
  -> submit_task_plan 保存选定 DAG + create_coding_worktree 创建隔离分支与目录
  -> analyze_only: code-analyzer -> analysis_report
  -> review_only: code-reviewer -> review_report(PASS / FAIL)
  -> implement_and_review:
       code-analyzer -> analysis_report
       -> code-implementer -> implementation_report
       -> code-reviewer -> review_report(PASS / FAIL)
  -> Review FAIL 经人工批准后：reanalyze -> fix -> rereview（复用原 Worktree）
  -> Lead Agent 汇总 coding_run
```

只有 `review_report` 明确为 `PASS` 时，整个 `coding_run` 才会标记为 `completed`。

## 架构与职责

| 模块 | 职责 |
| --- | --- |
| `skills/public/multi-agent-coding/` | 定义 Coding 工作流、人工计划审批、角色交接和输出契约 |
| `subagents/builtins/coding_agents.py` | 定义三个内置专业角色、提示词、工具白名单、工作区权限和产物类型 |
| `subagents/coding_artifacts.py` | 定义并校验 analysis / implementation / review 三类结构化报告 |
| `subagents/worktree_integrity.py` | 为只读分析与审查角色校验运行前后的 Git 可见工作区指纹 |
| `backend/packages/harness/deerflow/mcp_servers/github_issue.py` | 提供 GitHub Issue MCP 工具 |
| `backend/packages/harness/deerflow/task_graph/` | 定义 CodingTask、JSON 持久化、角色绑定、产物传递和 DAG 状态转换 |
| `submit_task_plan_tool.py` | 把模型生成的任务计划写入线程级 TaskGraph |
| `worktree_tool.py` | 校验目标仓库、创建 Git Worktree 并绑定 CodingTask |
| `task_tool.py` | 领取任务、启动 Sub-Agent、回写完成或失败状态 |
| `recover_coding_task_tool.py` | 验证人工重试批准并恢复技术失败任务 |
| `continue_after_review_tool.py` | 验证审查 FAIL 后的人工批准，追加重新分析、修复和复审任务 |
| `SubagentExecutor` | 运行一次具体 Sub-Agent 调用 |
| `ThreadDataMiddleware` | 为子 Agent 保留已验证的 Worktree 工作区 |

### 两类任务身份

```text
coding_task_id
  = 稳定业务任务身份
  = 例如 coding-analysis / coding-implementation / coding-review；审查续跑会追加 reanalysis / fix / rereview 节点

tool_call_id
  = 某一次 Sub-Agent 执行身份
  = 同一个失败任务重试时会产生新的调用 ID
```

TaskGraph 管理长期业务状态，SubagentExecutor 管理一次真实执行，`task_tool` 负责把二者连接起来。

## 快速开始

### 1. 环境要求

- Python 3.12+
- Node.js 22+
- pnpm
- Git
- Make（Windows 可在 Git Bash 中运行）

### 2. 初始化

```bash
git clone https://github.com/acvz1/deer-flow.git
cd deer-flow
make setup
```

按照 Setup Wizard 配置模型和本地 Sandbox。实际配置写入根目录的 `config.yaml` 与 `extensions_config.json`，这两个文件不会提交到 Git。

### 3. 启动

```bash
make dev
```

浏览器访问：<http://localhost:2026>

也可以使用 Docker：

```bash
make up
```

### 4. 发起 Coding Run

在支持 Sub-Agent 的对话模式中激活：

```text
/multi-agent-coding
```

然后提供完整任务：

```yaml
repository_path: D:\Project\example-repo
coding_brief:
  goal: 修复购物车折扣计算
  acceptance_criteria:
    - 正确计算折后总价
    - 非法折扣率抛出 ValueError
    - 现有测试全部通过
  tasks:
    - 阅读 pricing.py 和测试
    - 实现最小修复
    - 运行测试并独立审查
  open_questions: []
```

Agent 会先展示计划并请求批准。批准后才会保存 DAG、创建 Worktree 和启动 Sub-Agent。

## Task DAG 状态流转

```text
pending
  -> claim()：依赖全部完成后领取
  -> in_progress
     -> complete() -> completed
     -> fail()     -> failed
                       -> 人工批准
                       -> recover()
                       -> pending
```

任务按照 `user_id + thread_id` 保存到独立目录，因此不同用户和线程不会共享 CodingTask 状态。

## Worktree 隔离

假设目标仓库为：

```text
D:\Project\example-repo
```

一次名为 `coding-run` 的执行会创建：

```text
工作目录：D:\Project\example-repo\.worktrees\coding-run
分支：coding/coding-run
```

分析、实现和审查 Agent 共享这一个 Worktree，因此后续角色可以看到前序改动；用户原工作区的文件、当前分支和暂存区不会被切换。

模型只使用统一虚拟路径 `/mnt/user-data/workspace`。本地 Sandbox 根据当前线程上下文映射到真实 Worktree，并拒绝访问绑定目录之外的宿主机路径。

## 验证结果

项目已在独立外部示例仓库完成真实 E2E：

```text
人工计划审批：通过
任务链：analyzer -> implementer -> reviewer
修改位置：独立 Git Worktree
测试：5 / 5 passed
审查：PASS
主工作区：无受跟踪文件修改
```

相关回归测试覆盖内置角色与工具边界、结构化报告校验、DAG 角色绑定与产物传递、Worktree 创建与绑定、只读指纹、人工恢复、生产工具注册和路径安全边界。

运行核心测试：

```bash
cd backend
uv run pytest \
  tests/test_task_graph_models.py \
  tests/test_task_graph_store.py \
  tests/test_task_graph_service.py \
  tests/test_task_graph_factory.py \
  tests/test_coding_subagents_config.py \
  tests/test_coding_artifacts.py \
  tests/test_worktree_integrity.py \
  tests/test_task_tool_coding_task.py \
  tests/test_recover_coding_task_tool.py \
  tests/test_continue_after_review_tool.py \
  tests/test_coding_workflow_tool_registration.py -q
```

## 与上游 DeerFlow 的边界

| 能力 | 来源 |
| --- | --- |
| LangGraph Agent Loop、Checkpoint、Sandbox、MCP 客户端、Skill 加载、基础 Sub-Agent | DeerFlow / LangGraph 上游 |
| GitHub Issue MCP、Coding Skill、三个源码内置专业角色 | 本项目新增 |
| 结构化报告校验、DAG 自动交接与只读角色 Worktree 指纹 | 本项目新增 |
| 持久化 Coding Task DAG、角色绑定与失败恢复 | 本项目新增 |
| 外部 Git Worktree 创建、绑定和运行时路径接线 | 本项目新增 |
| 计划审批与任务级人工重试确认 | 本项目新增 |

## 当前限制

- TaskGraph 当前使用 JSON 文件持久化，尚未增加跨进程任务领取锁。
- `CodingTask.completed` 表示阶段执行结束，不等同于业务审查结果 `PASS`。
- 任意本地磁盘仓库目前仅支持可信 `LocalSandboxProvider`；其他 Sandbox 会显式拒绝。
- Worktree 基于已提交的 `HEAD` 创建，目标仓库未提交的修改不会自动复制进去。
- 当前流程不会自动合并分支、推送远端或创建 PR。
- 失败恢复会保留最近一次失败原因，并在下一次子 Agent 启动时作为排查线索注入；尚未保存完整的多次尝试历史。
- 只读角色采用“运行前后 Git 可见状态一致”的结果校验，而不是操作系统级只读挂载；被 `.gitignore` 忽略的测试缓存不计入持久代码改动。

## 致谢与许可证

本项目基于 ByteDance 开源的 [DeerFlow](https://github.com/bytedance/deer-flow) 进行二次开发。

许可证见 [LICENSE](./LICENSE)。
