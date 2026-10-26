# Management handoff, version 1

This contract is extension-owned and experimental. It deliberately avoids a second core registry: the existing `PluginContribution`, contributed router and principal/authorization bridge are sufficient. Third-to-fifth-stage consumers can integrate the HTTP contract without installing a management page. They must not treat this document as a claim that space authorization or a Trace service has been implemented.

## Identity and resources

`ManagementContext.principal` is resolved by the host, not deserialized from JSON. The initial implementation accepts only explicitly granted administrators. The connection ID selects operator configuration; it is neither a tenant credential nor a logical space ID. No executing Agent or space is implied by an interactive HTTP call. Future delegated contexts must be host-verified before resource operations; a client-supplied Agent/space cannot extend permissions.

Resource identity is `(provider, connection_id, native_base_id, document_id)`. `dataset_id` is the retrieval-facing identity, maintained consistently with the corresponding retrieval adapter. A management result does not create a scope grant or a citation; only the existing retrieval evidence validation can do that. Same-named bases on different connections must not be merged.

## Capabilities and requests

Each base returns the intersection of configured management operations and the adapter's supported surface. `pipeline` describes the configured Provider's support, not observed task execution. The presence of a stage does not authorize a write. Unrecognized inputs and unavailable operations must fail rather than widen the request or silently drop options.

Processing options reflect each base: graph controls require graph support; chunk controls require a valid non-parent-child chunking configuration. Local credential validation fails before HTTP with `ManagementCredentialUnavailable`, mapped to `503` without reconciliation guidance.

The supplied WeKnora adapter exposes ingest, status, reprocess and cancel. Upload returns the Provider's native document identity. The Provider owns queues, parser/chunker/embedding work, Wiki generation, entity extraction and index storage. No local scheduler is involved.

## State and uncertainty

Document snapshots normalize upstream state without creating local task IDs. Polls always recheck authorization. A newer upstream state remains `unknown` until its semantics are explicitly mapped. A searchable document can still be `running` while enrichment proceeds. A terminal document state does not imply every optional stage succeeded.

No timestamp, attempt ID, percentage or step success is invented. The future Trace adapter must consume actual Provider events/spans, independently authorize them, and link them by connection/base/document (and upstream attempt when available). Raw source text and upstream error bodies are not part of this contract. Full Trace retention and sensitive-data policy remain with that separate extension.

Submitting a mutation has no automatic retry. A response loss may leave an accepted upstream operation. A consumer must reconcile before retrying; there is no local durable exactly-once promise. For a future durable workflow, add persistent admission/reconciliation before advertising retry-safe request IDs.

Server-side warning logs distinguish transport exception types, HTTP status and
malformed/oversized response categories. Logs omit exception messages, tracebacks,
request URLs and provider payloads because these can contain credentials or source
content. These diagnostics do not provide durable admission or processing Trace.

## Compatibility

No changes are made to `knowledge_scope`, retrieval tools, source artifacts, frontend citation models or stored messages. Offline fixtures in `backend/tests/test_knowledge_management_extension.py` demonstrate shared dataset identity and citation replay with the existing WeKnora read-only provider. Synthetic fixture transitions are not live processing evidence.
