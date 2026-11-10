# Optional knowledge library, contract v1

Added in management/platform **0.1.1**. These extension-owned contracts provide
phase-4 page capabilities without changing core retrieval or requiring every
management Provider to implement a library. `library(context, connection,
native_base, operation, payload)` is optional; missing methods are unsupported.

## Routes and permissions

Routes use `/api/extensions/knowledge-platform/spaces/{space}/resources/{resource}`:

| Method/path | Operation grant | Result |
| --- | --- | --- |
| GET `/library/documents` | `documents` | Paginated titles and processing snapshots |
| GET `/library/entries` | `entries` | Paginated metadata; no content or summary |
| GET `/library/entry?entry=concept/cedar` | `entry` | Current full entry and version |
| GET `/library/revisions?entry=concept/cedar` | `revisions` | Historical metadata; no current body |
| GET `/library/revision?entry=concept/cedar&version=1` | `revision` | Historical title/content/summary |
| PUT `/entry` | `entry_edit` | Guarded title/content update |
| POST `/entry/restore` | `entry_restore` | Guarded restoration as a new version |
| GET `/library/graph?search=Cedar` | `graph` | Bounded entities, real edges and evidence |

GETs require host `read` for both knowledge-platform and knowledge-management;
writes require both `write` scopes. All retain the administrator floor, exact
space membership/resource/operation policy and Provider user/base/operation
grants. Recheck policy after capability I/O, before Provider invocation, and
before returning data. Page visibility and pipeline support are not grants.

`page` is 1–10,000, `page_size` 1–50, and `search` at most 500 characters.
`state` is an explicit parse-state filter for documents. No queue-job IDs,
timings, retries or stage progress are inferred. `entry` allows bounded
hierarchical slugs but rejects traversal, encoded path fragments, controls,
empty path segments and URL delimiters.

Edit: `{"entry":"concept/cedar","expected_version":2,"title":"Cedar","content":"Text"}`.
Restore: `{"entry":"concept/cedar","expected_version":2,"version":1}`.
Other body fields are rejected. Mutations never retry; transport errors and
post-write policy changes can leave an accepted upstream change. Reconcile
before retrying. There is no exactly-once admission or persistent task store.
Entry edit bodies have an 8 MiB byte ceiling to fit the 500,000-character limit,
including JSON surrogate escaping; policy and other JSON bodies remain 1 MiB.
Provider input errors return 422, while invalid Provider responses return 502.
Directory rows use `EntrySummary`; full content/summary requires `entry` or
`revision`. A list grant never implicitly grants a full-body read.

## WeKnora mapping

Verified against **v0.8.3**, commit
`3e22822c1d2397be730c458c7539d0eb8c113a24`:

- Documents: GET `/api/v1/knowledge-bases/{base}/knowledge`, with page/page_size,
  keyword and parse_status. Validate every document's base membership.
- Entries: GET `/api/v1/knowledgebase/{base}/wiki/pages`, plus `/pages/{slug}`.
- History: GET `/wiki/revisions/{slug}`, with offset/limit or one version;
  verify base, slug, version and historical page identity. Historical `content`
  uses `omitempty`: omission means an empty body; current-page reads still
  require a content field.
- **No Wiki mutations in v0.8.3.** Its PUT handler checks the submitted version,
  but the service re-reads the page and uses that later version in the atomic
  update. A concurrent write between reads can therefore be overwritten.
  Both `entry_edit` and `entry_restore` are removed from capabilities and rejected
  by direct adapter calls before upstream I/O. Grants cannot override this gate.
  Another GET or local lock cannot protect against other upstream writers.
  Re-enable only after verifying an upstream fix carries the caller version
  through the atomic write. `/wiki/revert` also lacks the required caller guard.
  The generic extension routes/UI remain available to capable Providers.

Only bases with `capabilities.wiki == true` offer entry operations. Editable
title/content/summary limits are 500/500,000/10,000 characters. Reject over-limit,
missing full content or credential-bearing text rather than writing truncated
or redacted content. Display-only document titles are bounded and redacted.
Submitted entry fields containing the configured credential are rejected before
upstream I/O, including when mutations are unsupported. HTTP responses are capped
at 4 MiB. Conflicts return 409 without retry.

The graph pipeline describes extraction, not graph querying. There is no stored
entity-relation query API in this version; `/wiki/graph` contains page links and
is not substituted. System-admin runtime queues span resources and are not used
as a space directory.

Add desired operations to **both** WeKnora `grants[].operations` and platform
operator `resources[].operations`, retaining `capabilities`. For example:

```yaml
operations: [capabilities, status, documents, entries, entry, revisions, revision]
```

Existing operator resources retain the legacy seven default operations, so an
upgrade grants no new library reads or writes. Space/connection/default policy
can narrow the operator ceiling. Viewer roles may receive library reads, but
the unchanged host administrator floor still applies to management HTTP.

## LightRAG graph mapping

Optional factory:
`deerflow_extension_knowledge_management.lightrag:LightRAGLibrary`. It uses the
same **v1.5.7 `/query/data`** shape as the existing retrieval extension. Each
connection binds one server workspace, whose native base is exactly `workspace`.
There is no client-controlled workspace header, selected-document filter or
fallback to another connection. Configure in knowledge-platform:

```yaml
connections:
  - id: graph
    provider: lightrag
    provider_factory: deerflow_extension_knowledge_management.lightrag:LightRAGLibrary
    provider_config:
      connections:
        - id: graph
          base_url: http://127.0.0.1:9621
          api_key_env: LIGHTRAG_API_KEY
          grants:
            - user_id: exact-host-user-id
              knowledge_base_ids: [workspace]
              operations: [capabilities, graph]
    resources:
      - base_id: workspace
        dataset_id: lr1_REPLACE_WITH_HASH
        operations: [capabilities, graph]
        tools: []
```

Compute `dataset_id` as `lr1_` plus SHA-256 of UTF-8
`json.dumps([base_url_without_trailing_slash, "workspace"], ensure_ascii=False)`
(Python default separators). This is a library workspace identity only; existing
LightRAG retrieval has no dataset-filter/catalog contract and gains none here.
Map the resource into an authorized space with the existing platform policy API.

Queries call POST `/query/data`, mode hybrid, top_k/chunk_top_k 50, without answer
generation. They may still incur upstream retrieval/keyword processing. Responses
are capped at 4 MiB, 200 entities, 100 relations and 100 evidence chunks. Invalid,
duplicate, overlong or credential-bearing IDs fail; descriptions/excerpts are
bounded and redacted. Evidence joins only exact `source_id` values split by
`<SEP>` to returned `chunk_id`. No edges are inferred from co-occurrence, layout
or file paths. Missing evidence is explicit; the graph is always a bounded view.
Explicit entities consume the same 200-node budget as endpoints added by real
relations; relations requiring nodes beyond the budget are omitted. Oversized
row arrays are projected to these bounds within the HTTP response byte cap.
Only the exact `failure` / `Query returned empty dataset.` response with empty
entity, relationship and chunk arrays becomes an empty graph; other failures
remain errors.

This graph-only Provider offers no ingestion, entry mutation, queue administration,
arbitrary upstream JSON or phase-5 Trace. Retrieval remains separately authorized;
library mappings never change chat Scope.
