---
name: multi-agent-coding
description: "Coordinate code analysis, implementation, and review through specialized subagents."
allowed-tools:
  - ask_clarification
  - submit_task_plan
  - create_coding_worktree
  - recover_coding_task
  - task
---

# Multi-Agent Coding

把一个已经确认的 `coding_brief` 依次交给分析、实现和审查子 Agent。保持单向流水线；本 Skill 不执行自动返工循环。

## Input Gate

1. 确认输入中存在一个 `coding_brief`，并且至少包含 `goal`、`acceptance_criteria` 和 `tasks`。
2. 如果缺少必要字段，停止执行并列出缺失字段，不要自行补全需求。
3. 如果 `open_questions` 中仍有会影响安全实现的问题，停止执行并要求用户先确认。

## Approval Gate

Input Gate 通过后，先调用一次 `ask_clarification`，参数固定为：

- `question`: `Approve this coding plan and start the isolated coding run?`
- `clarification_type`: `risk_confirmation`
- `context`: `coding_plan_approval`
- `options`: `Approve coding plan`、`Reject coding plan`

该调用会结束当前运行并等待用户回复。只有消息历史中匹配该请求的结构化回复明确选择 `Approve coding plan`，才能继续保存 DAG、创建 Worktree 或委派子 Agent。选择拒绝或没有匹配回复时停止，`failure_stage` 记为 `input`；不要把普通对话文字当成批准。

## Persist Task DAG

通过 Input Gate 后、委派任何子 Agent 前，先调用一次 `submit_task_plan`，保存下面三个稳定阶段任务。必须原样使用这些 ID 和依赖，不能用临时编号替换：

```json
[
  {
    "id": "coding-analysis",
    "subject": "Analyze coding brief",
    "description": "Inspect the real codebase and produce the analysis report.",
    "blocked_by": [],
    "agent_type": "code-analyzer"
  },
  {
    "id": "coding-implementation",
    "subject": "Implement coding brief",
    "description": "Implement the confirmed change and produce test evidence.",
    "blocked_by": ["coding-analysis"],
    "agent_type": "code-implementer"
  },
  {
    "id": "coding-review",
    "subject": "Review implementation",
    "description": "Independently review the implementation and verification evidence.",
    "blocked_by": ["coding-implementation"],
    "agent_type": "code-reviewer"
  }
]
```

只有 `submit_task_plan` 成功保存整张 DAG 后才能开始委派。任务状态由 `task(coding_task_id=...)` 根据真实 Sub-Agent 终态自动回写，DAG 会拒绝错误角色领取任务。子 Agent 返回值还必须通过对应 JSON 结构校验，校验后的报告才会写入任务并自动交给下游；不要根据报告文字手工宣称任务已完成。

## Prepare Isolated Worktree

保存 DAG 后、委派任何子 Agent 前，先确认用户明确指定了要修改的本地 Git 仓库，然后调用一次 `create_coding_worktree`：

- `repository_path`: 用户为本次 Coding Run 选择的本地 Git 仓库绝对路径，可以位于任意磁盘
- `name`: `coding-run`
- `task_ids`: `coding-analysis`、`coding-implementation`、`coding-review`

该工具会在用户的目标仓库中创建并验证 `coding/coding-run` 分支对应的独立 Worktree，然后把完整 Worktree 路径绑定到三个阶段任务。子 Agent 修改目标项目的 Worktree；DeerFlow 自己的线程 Workspace 不是目标代码仓库。只有工具成功返回后才能开始 Analyze；创建或验证失败时立即停止，不得委派任何子 Agent。

## Workflow

### 1. Analyze

调用 `task`，参数必须包含：

- `description`: `Analyze coding brief`
- `subagent_type`: `code-analyzer`
- `coding_task_id`: `coding-analysis`
- `prompt`: 传入完整 `coding_brief`，要求基于真实代码返回 `analysis_report`

`analysis_report` 必须包含相关文件与依据、建议修改步骤、风险、测试计划和给实现 Agent 的明确输入。只有该任务返回 `completed` 才能继续。

### 2. Implement

调用 `task`，参数必须包含：

- `description`: `Implement coding brief`
- `subagent_type`: `code-implementer`
- `coding_task_id`: `coding-implementation`
- `prompt`: 传入原始 `coding_brief`，要求返回 `implementation_report`。已校验的 `analysis_report` 会由 `task` 工具自动注入，不要手工复制

`implementation_report` 必须包含修改文件、关键实现、实际运行的测试及结果、尚存风险和审查重点。只有该任务返回 `completed` 才能继续。

### 3. Review

调用 `task`，参数必须包含：

- `description`: `Review implementation`
- `subagent_type`: `code-reviewer`
- `coding_task_id`: `coding-review`
- `prompt`: 传入原始 `coding_brief`，要求返回 `review_report`。已校验的 `analysis_report` 与 `implementation_report` 会由 `task` 工具自动注入，不要手工复制

`review_report` 必须包含 `PASS` 或 `FAIL`、逐条验收结果、问题清单和测试证据。不要因为实现 Agent 声称测试通过就跳过独立审查。

## Failure Handling

If any delegation returns failed, do not claim success. 记录失败阶段对应的 `coding_task_id`，然后调用 `ask_clarification`：

- `question`: 说明真实失败阶段与原因，并询问是否重试该任务
- `clarification_type`: `risk_confirmation`
- `context`: `coding_task_recovery:{coding_task_id}`，把占位符替换为真实任务 ID
- `options`: `Retry failed task`、`Stop pipeline`

该调用会结束当前运行。只有匹配本任务请求的结构化回复选择 `Retry failed task` 后，才能调用 `recover_coding_task(coding_task_id=...)`，再使用原参数和已得到的完整上游报告重新调用同一个 `task`。选择 `Stop pipeline` 时直接返回失败。

Each retry requires a fresh human confirmation. Do not retry automatically. 如果重试后再次失败，必须重新走上述人工确认步骤；不得在一次确认后循环恢复或连续重试。

把已经得到的报告和失败原因原样保留在最终结果中。审查结果为 `FAIL` 时返回失败，不要在本 Skill 内自动重新调用实现 Agent。

## Output Contract

只返回一个 `coding_run`：

```yaml
coding_run:
  status: completed | failed
  coding_brief: original confirmed brief
  analysis_report: report or null
  implementation_report: report or null
  review_report: report or null
  failure_stage: input | analysis | implementation | review | null
  failure_reason: observed reason or null
```

只有 `review_report` 明确为 `PASS` 时，`coding_run.status` 才能是 `completed`。不得编造子 Agent 输出、文件修改或测试结果。
