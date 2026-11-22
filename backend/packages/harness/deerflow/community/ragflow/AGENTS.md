# RAGFlow knowledge provider (`deerflow/community/ragflow/`)

```bash
cd backend && python -m pytest tests -q -k "ragflow"
```

## Citation snapshots

- **The model sees citation links, and the tool artifact holds the evidence
  snapshots they resolve to.** Provider locators stay in the artifact. Source
  names and text are credential-redacted in both. IDs are unique per retrieval.
- **A snapshot keeps the exact excerpt that was sent to the model** and marks
  truncation. Do not fetch a fresh chunk and present it as historical evidence.
- **Budgeting drops whole entries, with an omission notice.** An excerpt is
  never shortened under an existing ID, and its source record leaves with it.
  Results that carry citations get no exemption from the budget.
- **Omission counts are computed, never trusted.** Filter omitted IDs against
  each outer report, deduplicate them, and let recaptured evidence replace an
  omission. Unknown prose links are not counted.
- **The source dialog reads stored thread messages.** It adds no
  unauthenticated document proxy.
- **The direct `knowledge_search()` function keeps its string API.**

## Document validation

- **RAGFlow ID syntax is checked in the client before any HTTP request.** It is
  a provider rule, so it is not applied to the generic knowledge contract.
- **Selected documents are validated in batches**, because the provider limits
  IDs per request. That limit is separate from the application's selection
  limit. Any batch error, missing document or non-searchable document rejects the
  whole scope.
