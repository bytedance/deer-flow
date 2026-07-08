# RAGFlow Metadata Filtering Reference (v0.26.1)

RAGFlow exposes **two** metadata filter formats on different endpoints. Do not mix them.

## Quick decision

| Goal | Endpoint | Filter field | Modes |
|------|----------|--------------|-------|
| SDK / external integration | `POST /api/v1/retrieval` | `metadata_condition` | Manual only |
| Dataset search UI / LLM-assisted filter | `POST /api/v1/datasets/search` | `meta_data_filter` | auto, semi_auto, manual |

Use the skill CLI:

- `ragflow_client.py retrieve ... --metadata-condition file.json`
- `ragflow_client.py search ... --meta-data-filter file.json`

## metadata_condition (retrieval endpoint)

Used by `POST /api/v1/retrieval` and the Python SDK `RAGFlow.retrieve()`.

Document-level filter applied **before** vector search. Filters documents by flattened metadata, then retrieves chunks only from matching docs.

```json
{
  "logic": "and",
  "conditions": [
    {
      "name": "author",
      "comparison_operator": "=",
      "value": "InfiniFlow"
    },
    {
      "name": "department",
      "comparison_operator": "contains",
      "value": "eng"
    }
  ]
}
```

### Supported comparison_operator values

- `contains`, `not contains`
- `start with`
- `empty`, `not empty`
- `=`, `≠`, `>`, `<`, `≥`, `≤`

Field name uses `"name"` (not `"key"`).

## meta_data_filter (datasets/search endpoint)

Used by `POST /api/v1/datasets/search` and `POST /api/v1/datasets/{id}/search`.

Supports LLM-assisted filter generation when RAGFlow has a chat model configured.

### manual

```json
{
  "method": "manual",
  "logic": "and",
  "manual": [
    {"key": "author", "op": "=", "value": "InfiniFlow"},
    {"key": "year", "op": "≥", "value": "2024"}
  ]
}
```

Manual ops: `=`, `≠`, `>`, `<`, `≥`, `≤`, `contains`, `not contains`, `in`, `not in`, `empty`, `not empty`, `start with`.

Field name uses `"key"` (not `"name"`).

### auto

LLM reads all dataset metadata keys and infers filters from the question:

```json
{"method": "auto"}
```

Requires a configured chat model in RAGFlow tenant settings.

### semi_auto

LLM only considers selected metadata keys:

```json
{
  "method": "semi_auto",
  "semi_auto": ["author", {"key": "year", "op": "≥"}]
}
```

## Common retrieval parameters (both endpoints)

| Parameter | retrieve default | search default | Notes |
|-----------|-----------------|----------------|-------|
| `top_k` | 1024 | 1024 | Max chunks in vector stage |
| `similarity_threshold` | 0.2 | 0.0 | Min score to return |
| `vector_similarity_weight` | 0.3 | 0.3 | Weight vs keyword similarity |
| `keyword` | false | false | Enable keyword extraction |
| `use_kg` | false | false | Knowledge graph retrieval |
| `rerank_id` | — | — | Rerank model ID |

### Skill defaults (`query` / `run` via `routing.json`)

| Parameter | Skill default | RAGFlow field | Notes |
|-----------|--------------|---------------|-------|
| `recall_top_k` | 64 | `top_k` | Vector recall pool before rerank |
| `page_size` | 10 | `page_size` / `size` | Final chunks returned after rerank |
| `max_citations` | 10 | — | Citation sidecar limit (skill-side) |
| `similarity_threshold` | 0.2 | `similarity_threshold` | Min score to keep |

## Empty results

- `metadata_condition` with no matching docs → empty chunks (HTTP 200, code 0).
- `meta_data_filter` manual with no match → internal sentinel, also returns empty chunks.

## Source references (RAGFlow 0.26.1)

- `api/apps/restful_apis/chunk_api.py` — `/retrieval` + `metadata_condition`
- `api/apps/services/dataset_api_service.py` — `search()` + `meta_data_filter`
- `common/metadata_utils.py` — `apply_meta_data_filter()` (auto/semi_auto/manual)
- `sdk/python/ragflow_sdk/ragflow.py` — SDK `retrieve()` wrapper
