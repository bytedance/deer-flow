# 记忆系统改进 - 摘要

## 同步说明（2026-03-10）

本摘要已与 `main` 分支实现同步。
TF-IDF/上下文感知检索属于**计划中**，尚未合并。

## 已实现

- 在记忆注入中使用 `tiktoken` 进行准确 token 计数。
- 将 facts 注入到 `<memory>` 提示词内容中。
- 按置信度对 facts 排序，并受 `max_injection_tokens` 限制。

## 计划中（尚未合并）

- 基于近期对话上下文的 TF-IDF 余弦相似度召回。
- 为 `format_memory_for_injection` 增加 `current_context` 参数。
- 加权排序（`similarity` + `confidence`）。
- 在运行时提取/注入流程中实现上下文感知 fact 选择。

## 需要同步的原因

早期文档将 TF-IDF 行为描述为已实现，这与 `main` 中代码不一致。
该不一致已在 issue `#1059` 中跟踪。

## 当前 API 形态

```python
def format_memory_for_injection(memory_data: dict[str, Any], max_tokens: int = 2000) -> str:
```

`main` 目前不包含 `current_context` 参数。

## 验证指引

- 实现：`packages/harness/deerflow/agents/memory/prompt.py`
- Prompt 组装：`packages/harness/deerflow/agents/lead_agent/prompt.py`
- 回归测试：`backend/tests/test_memory_prompt_injection.py`
