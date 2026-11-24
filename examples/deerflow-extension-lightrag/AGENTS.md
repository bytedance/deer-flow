# LightRAG retrieval example

HTTP calls, connection bindings and response mapping stay in this package. It
uses the core contextual tool dispatcher and the unchanged source envelope. Live
results and their limits are in `VALIDATION.md`.

```bash
cd backend && python -m pytest tests -q -k "lightrag"
```

Responses in these tests are synthetic. The opt-in live checks need fixtures
that are already indexed, and the model loop needs `KNOWLEDGE_RUN_MODEL_TEST=1`.
A live test never uploads data and never enables API usage on its own.

- **An entity or edge summary is not a document excerpt.** Join `source_id` to a
  returned `chunk_id` only. Do not infer edges or multi-hop paths, and do not use
  `file_path` alone as evidence.
- **Reject a selected scope, a missing binding, an HTTP error and a redirect.**
  Do not retry with broader credentials.
- **A shared evidence chunk is emitted once, before the first edge that refers
  to it.** Every edge names the result positions of its evidence, so truncating
  the tail cannot leave an edge that points to omitted evidence.
- **At the hit limit, tell omitted evidence apart from evidence that was not
  retrieved.**
- **Build the SSL client off the event loop.**
