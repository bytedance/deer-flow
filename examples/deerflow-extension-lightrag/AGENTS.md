# LightRAG retrieval extension

Keep HTTP calls, connection bindings and response mapping in this package.
Use the core contextual tool dispatcher and unchanged source envelope.
Entity/edge summaries are not document excerpts. Join source_id to returned
chunk_id only; never infer edges or multi-hop paths, or use file_path alone as
evidence. Reject selected scope, missing bindings, HTTP errors and redirects
without retrying with broader credentials. Offload SSL client construction.
Tests: backend/tests/test_lightrag_relations_extension.py and the shared
three-tool suite. Their responses are synthetic. Separate opt-in checks in
backend/tests/test_knowledge_phase1_live.py require existing indexed fixtures;
the GLM loop requires KNOWLEDGE_RUN_MODEL_TEST=1. See VALIDATION.md for live
results and limits. Never let live tests upload data or silently enable API usage.

Shared graph evidence chunks are emitted once per returned chunk ID, before the
first referencing edge. Every edge names its evidence result positions; prefix
truncation therefore cannot leave a retained edge pointing to omitted evidence.

At the hit limit, distinguish omitted evidence from absent retrieved evidence.
Numeric settings reject YAML booleans before Pydantic coercion; keep this guard
on every added numeric field so `true` cannot silently become a short timeout or
one-result limit.
