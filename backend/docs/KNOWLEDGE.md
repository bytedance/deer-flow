# Read-only knowledge contract (#6269, phase 1)

`deerflow.knowledge` owns `RetrievalResult`, `RetrievalHit`, `KnowledgeSource`,
`KnowledgeCapabilities`, and the search-only `RetrievalProvider` protocol.
These depend on no knowledge management service, resource store, or catalog.
Existing RAGFlow scope admission and selection UI remain authoritative.
The shared contract does not add scope selection or WeKnora support to LightRAG.

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
