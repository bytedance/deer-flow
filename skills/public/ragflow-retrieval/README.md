# ragflow-retrieval skill

Query RAGFlow 0.26.1 knowledge bases with vector retrieval and metadata filtering.

## Quickstart (operator)

1. Mock mode works without a live RAGFlow server:
   ```bash
   python skills/public/ragflow-retrieval/scripts/ragflow_client.py retrieve \
     --mock \
     --question "metadata filtering" \
     --dataset-ids kb-demo-001 \
     --metadata-condition skills/public/ragflow-retrieval/example/metadata_condition.author.json \
     --out /tmp/mock.retrieval.json
   ```
2. For a real deployment, copy and edit the skill `.env`:

   ```bash
   cp skills/public/ragflow-retrieval/.env.example skills/public/ragflow-retrieval/.env
   ```

   ```env
   RAGFLOW_BASE_URL=http://your-ragflow:9380
   RAGFLOW_API_KEY=ragflow-...
   ```

   Scripts auto-load this file on startup (`ragflow_client.py`, `route_intent.py`).

3. If your RAGFlow tenant has no rerank model, keep `"rerank_enabled": false` in `routing.json` defaults.
4. Trigger the skill in chat: "用 RAGFlow 检索知识库，按 author 过滤".

## Layout

```
skills/public/ragflow-retrieval/
├── SKILL.md
├── README.md
├── .env.example
├── references/metadata_filter.md
├── example/
│   ├── mock_retrieval/chunks.json
│   ├── metadata_condition.author.json
│   └── meta_data_filter.manual.json
└── scripts/
    ├── retry.py
    ├── ragflow_client.py
    └── tests/
```

## Intent routing (信贷 vs 制度)

Users do **not** specify `dataset_id`. Configure once in `config/routing.json`:

```json
{
  "intent": "信贷",
  "dataset_id": "your-real-dataset-id",
  "dataset_name": "信贷"
}
```

Agent workflow: intent recognition → `route_intent.py resolve` → `ragflow_client.py retrieve`.

See `prompts/intent_routing.md` and `SKILL.md` §意图路由.

## Two API paths

| CLI | HTTP | Filter field | LLM auto-filter |
|-----|------|--------------|-----------------|
| `retrieve` | `POST /api/v1/retrieval` | `metadata_condition` | No |
| `search` | `POST /api/v1/datasets/search` | `meta_data_filter` | Yes (auto/semi_auto) |

See `references/metadata_filter.md` for JSON schemas.

## Tests

```bash
cd skills/public/ragflow-retrieval/scripts
python -m pytest tests/ -q
```
