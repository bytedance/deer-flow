# WeKnora read-only extension

Keep provider-specific code in this independently packaged extension. Use
`registry.knowledge_provider` and the public `deerflow.knowledge` contracts;
core owns scope admission, formatting, budgets and citation evidence.

API reference: WeKnora v0.8.3 at `3e22822c1d2397be730c458c7539d0eb8c113a24`.
Preserve per-request operator bindings and upstream authorization. Never turn
missing bindings, invalid selections, empty allowlists, or upstream failures
into an unrestricted search. Use KB-bound `hybrid-search` with optional
`knowledge_ids` and disabled context enrichment. The global search endpoint
rejects document targets for KB-restricted keys and unions base/document target
lists. Never broaden credentials to work around that. Verify result membership.
Reject malformed document totals and detail shapes as provider errors; reserve
permission errors for resource identity, membership and searchability failures.
Dataset IDs derive from endpoint/tenant/native base, not credentials or labels.

Tests live in `backend/tests/test_weknora_extension*.py`; live tests require
explicit opt-in and an already indexed instance. Do not fabricate a live result.
See README for version references, configuration and the authorization model.
