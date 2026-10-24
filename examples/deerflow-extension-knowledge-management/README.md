# Optional knowledge management extension

This package implements the first management slice of [#6269's second stage](https://github.com/bytedance/deer-flow/issues/6269#issuecomment-6336870813): document ingestion and provider-owned processing. It installs no frontend, model tools, database, parser, embedding model or index. Existing retrieval works without this package.

The supplied adapter targets **WeKnora v0.8.3**, commit `3e22822c1d2397be730c458c7539d0eb8c113a24`. API mappings were checked against its handlers and `superbuzzy/deer-flow`'s `community/weknora/documents.py`. This is a new independent extension using the current host contracts, not a merge of that branch.

## Installation and authorization

From the repository root:

```sh
make extension-install SOURCE=./examples/deerflow-extension-knowledge-management
```

Installation alone does not expose management routes. Configure the installed plugin's `config` in operator-owned `config.yaml`, then restart Gateway:

```yaml
plugins:
  - use: deerflow_extension_knowledge_management:install
    config:
      enabled: true
      provider_config:
        connections:
          - id: team-reference
            base_url: https://weknora.example
            tenant_id: "1"
            api_key_env: WEKNORA_MANAGEMENT_KEY
            grants:
              - user_id: exact-deerflow-admin-user-id
                knowledge_base_ids: [native-weknora-base-id]
                operations: [capabilities, status, upload, url, manual, reprocess, cancel]
```

Set the credential in the Gateway environment. Use a restricted upstream key with retrieval and ingestion rights only for the intended bases. A retrieval-only key will fail writes; the extension never substitutes a more privileged key. Disable by setting `config.enabled: false` or removing the extension, then restarting Gateway. There is no runtime settings override or separate page switch.

Every route requires all of:

1. Gateway authentication and its normal CSRF protection for writes.
2. Host `plugin_management` read/write authorization for `knowledge-management`.
3. A host-resolved administrator principal, excluding internal callers.
4. An explicit operator grant matching the exact host user, connection, native knowledge base and operation.
5. Upstream resource authorization using that connection's key. Existing documents must also belong to the selected base before processing mutations.

This initial authorization mode is **explicit administrator resource grants with service credentials**. It does not claim upstream user impersonation, general organization RBAC, Agent-delegated writes, or platform-space authorization. Existing WeKnora retrieval `user_ids` confer no management rights. The management grants do not grant retrieval access. Client-provided user, Agent, tenant and space fields are rejected. Future multi-user/space management must supply a separately reviewed authorization implementation; do not remove the administrator floor to imply those capabilities exist.

## HTTP contract, version 1

All routes have this prefix:

```text
/api/extensions/knowledge-management/connections/{connection}/bases/{base}
```

`connection` is the operator-defined connection ID; `base` is the native Provider base ID. Browser clients use DeerFlow's authenticated API and normal CSRF mechanism.

| Method and suffix | Request | Result |
| --- | --- | --- |
| `GET /capabilities` | None | Allowed operations, processing options, provider-managed stages |
| `POST /documents` | URL or manual JSON below | `202` with document processing snapshot |
| `POST /files?filename=guide.txt` | Raw `application/octet-stream`, at most 16 MiB | `202` with snapshot |
| `GET /documents/{document}` | None | Current upstream document processing snapshot |
| `POST /documents/{document}/reprocess` | Processing options object, or `{}` | `202` with upstream snapshot |
| `POST /documents/{document}/cancel` | `{}` | `202` with upstream snapshot |

Manual ingestion explicitly publishes the source, so it enters the upstream processing pipeline instead of remaining a draft:

```json
{"kind":"manual","title":"Guide","content":"Cedar evidence","processing":{"chunk_size":512,"chunk_overlap":64}}
```

URL ingestion delegates fetching and SSRF enforcement to WeKnora's validated URL-ingestion endpoint; DeerFlow does not fetch the URL:

```json
{"kind":"url","url":"https://example.com/guide","title":"Guide"}
```

File ingestion optionally accepts `X-Processing-Options` containing the same JSON processing options. JSON requests are limited to 2 MiB; manual text is limited to 1,000,000 characters. Filenames cannot contain path separators or header control characters. No client filesystem path is accepted.

The snapshot contains `version`, `provider`, `connection_id`, `dataset_id`, `document_id`, `state`, `provider_state`, and `searchable`. The WeKnora `dataset_id` uses exactly the existing retrieval adapter's endpoint/tenant/base identity. A completed document can therefore be selected in the existing chat scope selector when the separately configured retrieval connection authorizes it.

States are `queued`, `running`, `completed`, `failed`, `cancelled`, or `unknown`. New upstream statuses stay `unknown`; they are never interpreted as successful. `finalizing` is `running` and may already be searchable, matching the existing retrieval contract. Cancellation is not deletion or rollback of already written chunks. `202` confirms a provider response, not completed processing. A document's terminal parse status does **not** establish that every Wiki/graph enrichment succeeded.

Error semantics: `403` denied, `404` missing resource, `409` conflict, `413` size limit, `415` upload media type, `422` invalid/unsupported input, `502` upstream failure, `503` missing/invalid local management credential (no upstream request made). Raw upstream bodies and credentials are never returned. No writes are automatically retried, including on timeout, cancellation, malformed response or conflict. If delivery is uncertain, reconcile using the upstream catalog before resubmitting; this version does not promise exactly-once ingestion or persist admission records.

## Processing scope

| Pipeline part | Adapter behavior |
| --- | --- |
| Parse and chunk | Performed by upstream ingestion/reparse; bounded chunk size/overlap overrides |
| Vector indexing | Uses the upstream base's model and indexing configuration; capability describes availability |
| Summary | Optional `summary_enabled` override |
| Knowledge entry generation/update | Upstream Wiki pipeline of a Wiki-enabled base during ingestion/reparse; no standalone Wiki editing endpoint |
| Entity extraction, relations and graph indexing | Upstream graph pipeline; `graph_enabled: true` requires that the base already supports graph extraction |
| Retry/cancel | Explicit reprocess/cancel operations; no automatic retry or local worker |

Missing optional stages are reported as `unsupported`. Processing options are base-aware: graph controls require graph support, and chunk overrides are advertised only for a valid non-parent-child chunking configuration. The extension does not simulate them or accept arbitrary provider options. Parser engine credentials, model selection, Wiki settings and graph extraction schema remain operator-controlled in WeKnora; this API cannot change the base-wide policy. Chunk overrides preserve the upstream base’s other chunking settings. Bases using parent-child mode reject chunk size/overlap overrides with `422` before mutation because upstream derives their effective sizes separately; requests without chunk overrides retain that mode. WeKnora v0.8.3 cannot override a nonzero overlap with zero; this request is rejected instead of silently retaining the old value. Empty reprocess options preserve the stored upstream processing policy. The API does not claim independent execution or progress for each stage.

Platform connections/spaces, resource-sharing UI, a knowledge center, Trace persistence, Wiki page lifecycle editing and multi-hop graph algorithms remain separate work. Processing snapshots contain no raw Trace, source content or model prompts.

## Provider integration and tests

The router only consumes `contracts.ManagementProvider`. An operator can set `provider_factory` to another trusted `module:factory` implementing the optional management contract. This executable setting is not API-writable. Providers must enforce their own resource grants and upstream authorization in every operation and explicitly reject unsupported operations. See [CONTRACT.md](CONTRACT.md) for the handoff boundary.

Run offline tests from the repository root:

```sh
uv run --no-sync --project backend pytest backend/tests/test_knowledge_management_extension.py -q
uv run --no-sync --project backend pytest backend/tests/blocking_io/test_knowledge_management_extension.py -q
```

Tests use synthetic `httpx.MockTransport` responses. They cover ingestion → status → existing scope/retrieval → citation replay, denied identities/resources, upstream errors without credential fallback, request size limits, strict options, optional installation and a second test Provider. Blocking-I/O coverage exercises actual HTTPX/SSL initialization off-loop. These tests do **not** establish real upstream extraction/indexing quality or browser acceptance.

For live acceptance, use a dedicated test base and explicitly granted administrator: upload a unique test document, poll its document ID, confirm searchable state, select it in the existing chat scope selector, ask a question whose answer is unique to that source, and verify the citation after refreshing. Repeat with URL/manual ingestion and with Wiki/graph-enabled bases, checking upstream processing outcomes rather than inferring enrichment success from parse completion. Record upstream version and configuration; never commit credentials or document content. The offline suite never performs live writes. Real OrbStack/GLM-5.3/BGE acceptance, environment repairs and observed limitations are recorded in [VALIDATION.md](VALIDATION.md).


### Opt-in live regression

Use a dedicated synthetic test base and an authenticated, explicitly granted
administrator. Export these variables without committing their values:

- `DEER_FLOW_RUN_LIVE_TESTS=1` and `KNOWLEDGE_MANAGEMENT_ALLOW_WRITES=1`
- `KNOWLEDGE_GATEWAY_URL`: browser/Gateway origin, including scheme and port
- `KNOWLEDGE_SESSION_COOKIE`: value of the authenticated `access_token` cookie
- `KNOWLEDGE_CSRF_TOKEN`: matching CSRF cookie/header value
- `KNOWLEDGE_CONNECTION_ID`: configured management connection
- `WEKNORA_BASE_URL`, `WEKNORA_TENANT_ID`, `WEKNORA_KNOWLEDGE_BASE_ID`
- `WEKNORA_API_KEY`: separately scoped retrieval credential for that test base

```sh
uv run --no-sync --project backend pytest backend/tests/test_knowledge_management_extension_live.py -m live -q -s --override-ini=addopts=
```

Each run creates one uniquely marked synthetic manual document, prints its native
ID for reconciliation, polls for completion, and verifies document-scoped retrieval
and serialized citation evidence. It neither retries writes nor deletes fixtures.
If submission is uncertain, inspect the upstream catalog before rerunning. Without
both opt-ins the test skips; missing credentials after opt-in fail explicitly.
This API regression does not replace browser or upstream Wiki/graph inspection.
