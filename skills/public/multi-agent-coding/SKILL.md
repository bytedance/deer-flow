---
name: multi-agent-coding
description: "Coordinate code analysis, implementation, and review through specialized subagents."
allowed-tools:
  - submit_task_plan
  - task
---

# Multi-Agent Coding

把一个已经确认的 `coding_brief` 依次交给分析、实现和审查子 Agent。保持单向流水线；本 Skill 不执行自动返工循环。

## Input Gate

1. 确认输入中存在一个 `coding_brief`，并且至少包含 `goal`、`acceptance_criteria` 和 `tasks`。
2. 如果缺少必要字段，停止执行并列出缺失字段，不要自行补全需求。
3. 如果 `open_questions` 中仍有会影响安全实现的问题，停止执行并要求用户先确认。

## Persist Task DAG

通过 Input Gate 后、委派任何子 Agent 前，先调用一次 `submit_task_plan`，保存下面三个稳定阶段任务。必须原样使用这些 ID 和依赖，不能用临时编号替换：

```json
[
  {
    "id": "coding-analysis",
    "subject": "Analyze coding brief",
    "description": "Inspect the real codebase and produce the analysis report.",
    "blocked_by": []
  },
  {
    "id": "coding-implementation",
    "subject": "Implement coding brief",
    "description": "Implement the confirmed change and produce test evidence.",
    "blocked_by": ["coding-analysis"]
  },
  {
    "id": "coding-review",
    "subject": "Review implementation",
    "description": "Independently review the implementation and verification evidence.",
    "blocked_by": ["coding-implementation"]
  }
]
```

只有 `submit_task_plan` 成功保存整张 DAG 后才能开始委派。任务状态由 `task(coding_task_id=...)` 根据真实 Sub-Agent 终态自动回写；不要根据报告文字手工宣称任务已完成。

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
- `prompt`: 传入原始 `coding_brief` 和完整 `analysis_report`，要求返回 `implementation_report`

`implementation_report` 必须包含修改文件、关键实现、实际运行的测试及结果、尚存风险和审查重点。只有该任务返回 `completed` 才能继续。

### 3. Review

调用 `task`，参数必须包含：

- `description`: `Review implementation`
- `subagent_type`: `code-reviewer`
- `coding_task_id`: `coding-review`
- `prompt`: 传入原始 `coding_brief`、完整 `analysis_report` 和完整 `implementation_report`，要求返回 `review_report`

`review_report` 必须包含 `PASS` 或 `FAIL`、逐条验收结果、问题清单和测试证据。不要因为实现 Agent 声称测试通过就跳过独立审查。

## Failure Handling

If any delegation returns failed, stop the pipeline and do not claim success.

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
