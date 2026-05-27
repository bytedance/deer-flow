# 记忆系统改进

本文档用于跟踪记忆注入行为及路线图状态。

## 状态（截至 2026-03-10）

已在 `main` 实现：
- 在 `format_memory_for_injection` 中通过 `tiktoken` 进行准确 token 计数。
- 在提示词记忆上下文中注入 facts。
- 按置信度（降序）对 facts 排序。
- 注入遵守 `max_injection_tokens` 预算。

计划中 / 尚未合并：
- 基于 TF-IDF 相似度的 fact 检索。
- 用于上下文感知评分的 `current_context` 输入。
- 可配置的相似度/置信度权重（`similarity_weight`、`confidence_weight`）。
- 在每次模型调用前接入中间件/运行时进行上下文感知检索。

## 当前行为

当前函数：

```python
def format_memory_for_injection(memory_data: dict[str, Any], max_tokens: int = 2000) -> str:
```

当前注入格式：
- 来自 `user.*.summary` 的 `User Context` 部分
- 来自 `history.*.summary` 的 `History` 部分
- 来自 `facts[]` 的 `Facts` 部分，按置信度排序，并在达到 token 预算前持续追加

Token 计数：
- 可用时使用 `tiktoken`（`cl100k_base`）
- 若 tokenizer 导入失败，则回退为 `len(text) // 4`

## 已知缺口

本文档此前版本曾将 TF-IDF/上下文感知检索描述为“已上线”。
这与 `main` 分支实际情况不符，并引发了混淆。

Issue 参考：`#1059`

## 路线图（计划）

计划中的评分策略：

```text
final_score = (similarity * 0.6) + (confidence * 0.4)
```

计划中的集成形态：
1. 从过滤后的用户/最终助手轮次中提取最近对话上下文。
2. 计算每个 fact 与当前上下文之间的 TF-IDF 余弦相似度。
3. 按加权分数排序，并在 token 预算内注入。
4. 若上下文不可用，则回退为仅按置信度排序。

## 验证

当前回归覆盖包括：
- 记忆注入输出中包含 facts
- 按置信度排序
- 在 token 预算限制下的 fact 注入

测试：
- `backend/tests/test_memory_prompt_injection.py`
