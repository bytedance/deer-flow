# Read-only knowledge contract (#6269, phases 1–3)

`deerflow.knowledge` owns `RetrievalResult`, `RetrievalHit`, `KnowledgeSource`,
`KnowledgeCapabilities`, and the search-only `RetrievalProvider` protocol.
Search-only providers need no knowledge management service, resource store,
catalog, or scope-filter implementation. Scope admission, the read-only catalog
and selection UI consume the same operation-level capabilities. LightRAG still
does not advertise dataset/document filters. The phase 3
[WeKnora extension](../../examples/deerflow-extension-weknora/README.md) implements
all six read-only operations against the v0.8.3 API.

## Provider registration and optional operations

An operator-installed extension calls
`registry.knowledge_provider(name, provider)` during `install()`. The method
returns `False` on older hosts and is supported by extension-api **0.2.7**.
The provider implements the existing `RetrievalProvider.search(query)` and
advertises `KnowledgeCapabilities`. Registration validates each advertised
operation, rejects duplicate/reserved names, and participates in source
attribution and positional install rollback. Connection settings, response
mapping and credentials belong to that extension's `plugins[].config`.
The contract package remains dependency-free; providers use the published
`deerflow.knowledge` models from the harness.

| Operation | Optional interface | Behavior |
| --- | --- | --- |
| `search` | `RetrievalProvider.search` | Required; returns `RetrievalResult` |
| `sources` | Existing result/source models | Advertises attributable evidence |
| `catalog` | `RetrievalCatalogProvider.catalog` | Paginated accessible datasets |
| `documents` | `RetrievalDocumentsProvider.documents` | Paginated documents in an accessible dataset |
| `dataset_filter` | `ScopedRetrievalProvider.search_scoped` | Enforces selected dataset IDs |
| `document_filter` | `ScopedRetrievalProvider.search_scoped` | Enforces document IDs within selected datasets |

Both catalog methods receive `context`, `page`, `page_size` and `search`, and
return `RetrievalCatalogPage` with `{id, name, selectable}` items. IDs are opaque
provider identifiers, including non-UUID identifiers. Gateway validates this
bounded public projection and never returns raw provider payloads.
Dataset and document IDs are limited to **256 Unicode code points** throughout
catalog output, URL parameters and scope snapshots. Overlong IDs are rejected,
never truncated. The WeKnora extension maps endpoint/tenant/base tuples to stable
`wk1_` SHA-256 IDs (68 ASCII characters), resolving them from the authorized
catalog on each request without a mapping store. The earlier `ks1_` encoding
allowing 512 characters is not the public contract. Reuse provider API/mapping logic without adding a second discovery
protocol or a DeerFlow ACL store.

`KnowledgeRequestContext` supplies the host user ID, Agent name and optional
execution-only scope. A provider implementing `search_scoped` receives context
on every search, including unrestricted searches. A search-only implementation
may retain `search(query)` when it uses an operator-owned connection with a
fixed resource visibility. User/tenant mappings and resource authorization
remain provider responsibilities; DeerFlow does not infer tenants from client
metadata or create a second ACL store.
`agent_name` identifies the current executor: the selected assistant name,
defaulting to `lead_agent`, or the executing subagent's configured name from
its server runtime `agent_id`. It does not identify the parent assistant.
Runtime context takes precedence over legacy `configurable.agent_name` for
primary runs, matching Agent assembly. Public Gateway and standalone LangGraph
run admission discard caller-supplied `is_subagent` and `agent_id`; only the
internal executor can assign child identity.
Standalone primary-run admission explicitly overrides persisted assistant
child-identity defaults, and assistant writes discard these reserved fields.
Catalog requests use the selected assistant name under the same convention;
direct provider callers outside the host runtime may omit it. Delegation
preserves the parent user identity and execution scope, while the provider
must enforce access for the executing agent on every call.

The Agent tool entry for registered providers is:

```yaml
knowledge_base:
  enabled: true
  scope_selection_enabled: true
tools:
  - name: knowledge_search
    group: knowledge
    use: deerflow.knowledge.tools:knowledge_search_tool
    provider: my-provider
```

`provider` selects an already registered operator-controlled name. The core tool
validates normalized results and uses phase 1's source formatter/budget. The
run's AppConfig and immutable extension snapshot take precedence over global
configuration and the global registry;
ordinary and batch subagents retain their inherited execution scope. Existing
RAGFlow and LightRAG tool paths remain valid. RAGFlow's compatibility adapter
owns its API calls, operator allowlist, searchable-document checks and catalog
mapping; native citation writers and direct text APIs remain unchanged.
Its HTTP client accepts only ASCII letters, digits, underscores and hyphens
in dataset IDs used as path segments. Traversal and encoded URL delimiters
are rejected before any document-list request, for both browsing and scope
validation. Other providers retain their own opaque-ID syntax.

See [the packaged synthetic Provider example](../../examples/deerflow-extension-knowledge/README.md)
for an offline catalog → selected document → retrieval → captured source flow.
The existing `ModelTool(response_format="content_and_artifact")` and
`PluginToolResult` channel from #6861 is unchanged. Custom ModelTools can still
emit the phase 1 envelope; artifact evidence must pass core validation.

## Scope admission and selection

`GET /api/knowledge/capabilities?agent_name=...` returns supported operations for
the exact assistant and whether selection UI is enabled. `/api/features` enables
the shared selector only when `knowledge_base.enabled` and
`scope_selection_enabled` are true and the provider supports both `catalog` and
`dataset_filter`. The selector exposes files only with both `documents` and
`document_filter`. It preserves older selected documents and blocks Apply if
the current provider cannot enforce them. Capability failures do not enable
catalog queries. Historical scope labels remain display-only.

The existing authenticated endpoints remain:

- `GET /api/knowledge/retrieval-catalog/datasets`
- `GET /api/knowledge/retrieval-catalog/datasets/{dataset_id}/documents`

Catalog operations require `threads:read`, the assistant's knowledge tool
access, the operator UI flag and the advertised operation. Providers return
only resources accessible to their connection/current user. A denied resource
returns 403; missing datasets return 404; unsupported operations return 409;
unconfigured retrieval returns 503; invalid provider output/failures return 502.
Errors do not disclose provider credentials or raw exception messages.

Scope stays in the existing version-one HumanMessage snapshot and server-owned
runtime key. Admission rejects unsupported dataset/document filters with 422,
independently of UI availability. Execution checks capabilities again before
calling the provider. Selected IDs constrain retrieval but never grant access;
missing/inaccessible resources fail the complete constrained request, with no
unrestricted retry. `all` means the provider's accessible operator scope and
`disabled` blocks knowledge search. Search-only providers can accept these
nonfiltering modes without catalog support. Regeneration and resume recover
the original server snapshot; they do not adopt a changed Agent default.

## Sources and citations

A source requires `provider`, a real document `title`, and retrieved `excerpt`.
Optional `dataset_name`, HTTP(S) `url`, and positive integer `page` must come
from actual provider evidence. Never derive pages from chunk ordinals or URLs
from local file paths. Unattributed chunks remain usable text without citations.

Opaque IDs hash the provider, title, excerpt, and supplied locators. Provider
dataset UUIDs, chunk IDs, and response-local reference IDs are not exposed in
citations. The model uses `[citation:Title](#knowledge-source-ID)` to refer to
the exact evidence. Both StructuredTools use `content_and_artifact`, with this
envelope on `ToolMessage.artifact`:

```json
{
  "knowledge_sources_version": 1,
  "knowledge_sources": [
    {
      "id": "<32 lowercase hex characters>",
      "provider": "lightrag",
      "title": "docs/guide.md",
      "excerpt": "Actual retrieved document text"
    }
  ]
}
```

Existing streaming, checkpoints, and run-event serialization preserve that
artifact. Readers require the envelope version, valid source fields, the source
handle, and actual excerpt in tool content. Backend readers recompute source IDs.
Assistant labels do not establish evidence. Gateway run input and checkpoint
writes strip the reserved source keys from caller artifacts.

The reserved envelope keys are the shared reader's trust boundary, not the
tool name. Server-side producers that write these keys become evidence
authorities and must supply validated retrieval evidence; naming a tool
`knowledge_search` grants no authority to caller artifacts. This allows new
provider tools without extending a name allowlist. Native RAGFlow readers
continue to apply their existing tool-name allowlist.
The wire schema lives at `contracts/knowledge_sources.v1.json`; backend and
frontend tests pin the version, field bounds, and source IDs to that schema.

Complete RAGFlow responses retain the native version-one
`knowledge_sources: {version, sources}` snapshots and `#knowledge-ID` links
already supported by the Gateway, frontend, ordinary tasks, and durable batch
exports. RAGFlow responses without complete provider locators fall back to the
shared contract above; LightRAG uses it directly. Both formats remain readable
after replay. When a task cites both formats, native RAGFlow snapshots stay in
`knowledge_sources`, while shared records live in `retrieval_sources` with
`knowledge_sources_version: 1`. Readers validate the same evidence and version;
Gateway strips all three keys from untrusted writes. Budget pruning must not
overwrite a native snapshot with shared records.

The shared envelope is the intended default for new provider integrations.
Convergence should happen at adapter output boundaries: migrate newly produced
RAGFlow evidence to the shared form once native scope, budgets, delegation and
durable batch forwarding have equivalent coverage. Keep native readers for
persisted citations and exports; do not rewrite historical IDs or fabricate
missing locators. Removing native writers/readers requires a separate migration
proposal and compatibility tests, not a full migration in phase 1.

The frontend resolves citations against preceding tool messages in loaded thread
history, displaying provider, title, excerpt, and only supplied locators. Absent
evidence stays unresolved until loaded. Historical web citations retain their
existing display. Old numbered knowledge text lacks structured evidence, so
replay never invents metadata for it. Direct Python text APIs keep their format.
Inline shared references accept both the raw `#knowledge-source-ID` and the
sanitized `#user-content-knowledge-source-ID`; the sanitizer's DOM-clobbering
protection stays enabled. Missing or malformed references render inert labels.

`format_result` budgets chunk text and source evidence together: a cited hit
that cannot fit is omitted as a whole. Results display at most 100 hits, matching
the bounded artifact readers. Only displayed excerpts enter artifacts.
The global tool-output budget prunes evidence removed by truncation or
externalization and replaces complete orphan citations with their labels.
Subagents accumulate at most 100 validated sources across values frames before
terminal publication, surviving compaction. Ordinary `task` forwards only
sources whose handles appear in the child report, with a bounded evidence
appendix. Existing native RAGFlow durable batch forwarding is retained;
shared-contract durable batch forwarding is outside this phase.
The accumulator scans only the changed history suffix, restarting at changed
prefixes after compaction; null messages are treated as empty frames. The
frontend caches validation by immutable message object in a WeakMap, so repeated
stream updates do not rescan unchanged tool excerpts.

## Adapters and capabilities

Both tools advertise `search` and `sources` in
`metadata.knowledge_capabilities.operations`. Optional `catalog`, `documents`,
`dataset_filter`, and `document_filter` describe separate operations. Search
support implies none of them. These metadata fields do not replace existing
RAGFlow scope admission or change operator-configured retrieval scope.

RAGFlow maps normalized chunk content, document title, dataset name, and
`doc_aggs` title fallback. Dataset resolution, embedding-group ordering, access
errors, and credential redaction retain their existing behavior.

LightRAG consumes `/query/data` document chunks, joining missing `file_path`
through `chunks[].reference_id` and `references[].reference_id`. Entities and
relationships alone cannot produce document citations. Missing attribution and
`unknown_source` remain unattributed. The response fields were checked against
LightRAG v1.5.7, commit `28ff1b05f2ac3f3e6fa14dd2cd33656579bd0c9c`, in
[`convert_to_user_format` and `generate_reference_list_from_chunks`](https://github.com/HKUDS/LightRAG/blob/28ff1b05f2ac3f3e6fa14dd2cd33656579bd0c9c/lightrag/utils.py).
Neither adapter fabricates page numbers or public document URLs.

## Validation

Offline tests use explicitly synthetic API-shaped responses for real
StructuredTool execution, budgets, credential redaction, delegation, replay,
caller forgery, and frontend display. These are not live provider responses.

Verify actual retrieved evidence from an existing indexed LightRAG workspace
with the read-only opt-in check from `backend/`:

```bash
DEER_FLOW_RUN_LIVE_TESTS=1 \
LIGHTRAG_BASE_URL=http://localhost:9621 \
LIGHTRAG_EVIDENCE_QUERY='a question matching an indexed document' \
uv run pytest tests/test_knowledge_contract_live.py -m live -q
```

Set `LIGHTRAG_API_KEY` in the environment if required. This test performs no
upload or resource changes. It requires attributable hits and checks each
citation against the real returned chunk evidence.

## WeKnora read-only extension

The independently packaged `examples/deerflow-extension-weknora` registers
`weknora` through the existing registry. Its operator configuration binds exact
host users (and optionally current executor names) to credential environment
variables, endpoint, tenant and optional base allowlist. No automatic tenant
inference, default user binding, resource ACL storage or new core API is added.
All bound users share the configured credential's upstream visibility; the
plugin does not impersonate a WeKnora human user.

The adapter uses v0.8.3's KB-bound `hybrid-search` with `query_text` and optional
`knowledge_ids`, disabling context enrichment. This supports KB-restricted
read-only API keys; the global search endpoint rejects their document targets
and unions base/document target lists. Raw recall needs no chat/rerank model.
The adapter validates all selected resources, checks returned document
membership/status, and fails the request on access errors without retrying an
unrestricted search. A missing title remains unattributed; pages and URLs are
omitted because the mapped response does not establish those locators.

See the extension README for immutable API references, installation, limits and
opt-in real-provider verification. Offline synthetic responses exercise the
actual registry, Gateway catalog, ToolNode, shared evidence and replay path.
Live validation needs an indexed instance and is not implied by offline passes.
The extension's [validation record](../../examples/deerflow-extension-weknora/VALIDATION.md)
documents the local v0.8.3 / Ollama bge-m3 run.
