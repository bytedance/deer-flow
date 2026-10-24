# Optional knowledge management

Keep management business logic, provider configuration and HTTP API in this
independently installed extension. Core retrieval must never depend on it.
Use public principal/plugin authorization APIs; no host-internal imports.

Administration is opt-in, explicit exact-user/base/operation grants plus the
host administrator floor and upstream authorization. Retrieval bindings do not
confer writes. Do not accept client user/tenant/Agent/space identities, widen a
resource selection, retry writes, follow credential-bearing redirects or fall
back to other credentials. Check document/base membership before mutations.

Pin WeKnora mappings to v0.8.3 commit
3e22822c1d2397be730c458c7539d0eb8c113a24. Upload/URL may return 201.
Processing capabilities describe upstream configuration, not observed success.
Finalizing may be searchable, and unknown states must remain unknown. Never
claim Wiki/graph completion based on the document's terminal parse status.
Reject chunk size/overlap overrides before mutation on parent-child bases;
upstream derives effective sizes and overlap independently. Preserve base
chunking settings for supported overrides: v0.8.3 treats
parent-child mode as authoritative and ignores zero integer overrides. Reject
an unrepresentable zero overlap. Empty reparse options preserve the stored policy. Keep arbitrary credential,
model and parser configuration out of request bodies.

Tests belong in backend/tests/test_knowledge_management_extension.py and
backend/tests/blocking_io/test_knowledge_management_extension.py. Use mock
transport for offline tests and actual HTTPX SSL initialization for blocking-I/O
coverage. Keep simulated and real validation explicitly separate.

Live acceptance lives in backend/tests/test_knowledge_management_extension_live.py.
Require both DEER_FLOW_RUN_LIVE_TESTS and KNOWLEDGE_MANAGEMENT_ALLOW_WRITES;
use a dedicated synthetic base and caller-supplied session/CSRF credentials.
Preserve native IDs for uncertain-write reconciliation; no automatic write retry
or cleanup. Record real stage outcomes and lexical Wiki-search limitations in
VALIDATION.md separately from mock contract coverage.

Frontend discovery uses the knowledge-management namespace with English/Chinese
copy; catalog presence never activates routes or implies a management page.

Provider failure logs include only exception types, numeric HTTP status and fixed
response-failure categories. Never log exception text/chains, payloads, URLs or
credentials; caplog regressions exercise transport and custom-provider failures.

Capability options must reflect the fetched base: omit graph controls without
graph support and chunk overrides for missing/parent-child chunking config.
Local credential validation raises ManagementCredentialUnavailable before HTTP;
map it to 503 without uncertain-write reconciliation guidance.
