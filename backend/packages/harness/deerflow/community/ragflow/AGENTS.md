# RAGFlow citation snapshots

`knowledge_search_tool` returns native `content_and_artifact`: model-visible
`[citation:N](#knowledge-<opaque-id>)` links resolve to bounded
`artifact.knowledge_sources` version-one evidence snapshots. Provider locators
stay in the artifact; source names and text are credential-redacted in both
representations. IDs are unique per retrieval, never per-message ordinal IDs.
Only actual emitted entries get source records. Retain the exact excerpt sent
to the model and mark truncation; do not fetch a fresh chunk and present it as
historical evidence. Direct `knowledge_search()` callers retain its string API.
`sources.py` forwards only captured sources cited by ordinary subagent results,
with count/text budgets. The source dialog uses stored thread messages and
introduces no unauthenticated document proxy. Durable batch result storage and
standalone Markdown do not include native source artifacts.

Output budgeting retains complete evidence entries and their source records
together, including delegated results and model-request history. Never shorten
an excerpt under an existing ID. Drop entries that cannot fit, with an omission
notice, while preserving unrelated artifact fields. This honors per-tool and
fallback limits without exempting citation-bearing results from the budget.


## 文档校验

`tools.py` 将每个知识库的文档校验拆成最多 100 个 ID 的批次，所有批次共用
`_bounded_gather` 的并发上限 4。按输入顺序合并已验证的 ID，检索保持完整范围；
任一批次异常、文档缺失或不可检索都沿用整体拒绝路径。应用级 1000 份选择上限
与提供商单请求上限分别维护。回归见 `backend/tests/test_ragflow_tools.py`
的 `test_large_document_scope_*`。
