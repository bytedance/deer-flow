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

## Document validation

`tools.py` validates each dataset's selected documents in batches of at most
100 IDs. All batches share the `_bounded_gather` concurrency limit of four.
Merge validated IDs in input order to retain the complete retrieval scope;
any batch error, missing document, or non-searchable document rejects the
whole scope. Keep the application-level 1000-document selection limit separate
from the provider's per-request limit. Regression coverage lives in
`backend/tests/test_ragflow_tools.py` under `test_large_document_scope_*`.
