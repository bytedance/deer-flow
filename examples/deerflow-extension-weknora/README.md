# WeKnora read-only knowledge provider

An independently installable extension for the phase 3 read-only delivery of
[#6269](https://github.com/bytedance/deer-flow/issues/6269). It uses the existing
DeerFlow scope selector, generic `knowledge_search`, shared citation validation,
source budgets, delegation and history rendering. No extra frontend is needed.

The API mapping is checked against **WeKnora v0.8.3**, commit
[`3e22822c1d2397be730c458c7539d0eb8c113a24`](https://github.com/Tencent/WeKnora/tree/3e22822c1d2397be730c458c7539d0eb8c113a24).
Other releases require verification. Offline tests use explicitly synthetic responses. A real local deployment
with Ollama `bge-m3` has also passed; see [the validation record](VALIDATION.md)
for the exact environment, checks and limits.

## Choosing this extension or MCP

Use [WeKnora's built-in MCP server](https://github.com/Tencent/WeKnora/blob/3e22822c1d2397be730c458c7539d0eb8c113a24/website-docs/03-features/08-mcp.md)
when you want to expose WeKnora tools to DeerFlow or another MCP client.
Choose this read-only extension when you want DeerFlow's native knowledge-base
and document scope selector, shared citations, and retrieval evidence preserved
across delegated tasks and conversation replay.

## Install and configure

Requires a host containing phase 2 (#6904), extension-api >=0.2.7, and an indexed
WeKnora v0.8.3 workspace. From the DeerFlow repository root:

```bash
make extension-install SOURCE=/absolute/path/to/deer-flow/examples/deerflow-extension-weknora
```

Set `WEKNORA_API_KEY` in the Gateway process environment (or its Docker
container environment). Do not put a key into the URL or commit credentials.
Edit the installed plugin's existing record in root `config.yaml`, and merge
the knowledge/tool settings with your existing entries:

```yaml
plugins:
  - use: deerflow_extension_weknora:install
    enabled: true
    required: true
    config:
      timeout: 30
      match_count: 8
      spaces:
        - base_url: https://weknora.example.com
          tenant_id: "42"
          api_key_env: WEKNORA_API_KEY
          user_ids: ["YOUR_DEERFLOW_USER_ID"]
          # Optional restriction to exact current executor names, including
          # each subagent that should search. Omit to allow all agents for
          # the explicitly bound users.
          agent_names: ["lead_agent", "researcher"]
          # Optional operator restriction; omission permits bases visible to
          # this connection. An empty list is rejected, never treated as all.
          knowledge_base_ids: ["YOUR_WEKNORA_KB_ID"]

knowledge_base:
  enabled: true
  scope_selection_enabled: true

tool_groups:
  - name: knowledge

tools:
  - name: knowledge_search
    group: knowledge
    use: deerflow.knowledge.tools:knowledge_search_tool
    provider: weknora
```

Preserve extension-manager fields such as `name` and `package` if present;
replace the existing `knowledge_search` entry instead of adding a second one.
Restart Gateway after installation or configuration changes. Select a knowledge
base (optionally individual documents) using the chat's existing scope selector,
then ask a question matching indexed content. Sources show the retrieved title,
excerpt and base name. This adapter does not invent page numbers or source URLs
from chunk offsets, storage paths or response indexes.

`user_ids` are exact server-authenticated DeerFlow IDs, not display names or
model-supplied values. Resolve them from your deployment's user administration;
for an unauthenticated/single-user installation use its actual runtime user ID.
There is no default or wildcard binding. To bind multiple workspaces, add a
`spaces` entry per endpoint/tenant pair, each with its own explicit users and
credential environment variable. Configure each endpoint/tenant only once.

## Authorization and scope

Each operation resolves the trusted current user and executor against the
operator-owned connection bindings. It sends `X-API-Key` and `X-Tenant-ID` to
WeKnora, whose API-key permissions and workspace/resource authorization remain
final. The binding is a credential-routing decision: every listed user receives
the resource visibility of that credential, further restricted by the optional
base allowlist. It does **not** impersonate a WeKnora human user. Use dedicated
least-privilege keys and only bind users intended to share that visibility.

Tenant-scoped keys must match the configured tenant. Platform keys always need
an explicit tenant and user binding here; unbound platform discovery and
fallback-to-all behavior are not supported. Missing bindings or keys fail
closed. API-key roles/capabilities must allow base/document reads and knowledge
search; restricted keys that cannot enumerate the configured bases are rejected.

- `all` searches explicit accessible bases in the user's bindings, never an
  omitted target list. At most 100 bases across at most 20 bound spaces are
  supported; narrow larger connections with `knowledge_base_ids`.
- `selected` validates every base and document before searching. Unknown,
  inaccessible, disabled, or not-yet-searchable documents fail the complete
  request. WeKnora `completed` and `finalizing` documents with `enabled` status
  are selectable.
- Retrieval uses `POST /api/v1/knowledge-bases/{id}/hybrid-search` with
  `query_text` and optional `knowledge_ids`. The path fixes the authorized base;
  document IDs narrow it. Context enrichment is disabled to keep matched
  evidence within that selection. Mixed selections use a request per base.
  This raw-recall API needs only an embedding model, with no reranker or chat
  model. The global `/knowledge-search` API rejects document IDs with
  KB-restricted API keys, and combining base/document targets there uses union
  semantics. The adapter never broadens key permissions to work around that.
- Retrieved documents are checked against the authoritative detail endpoint for
  base membership and searchable state; unexpected evidence fails the request.
  No unrestricted retry, partial result on an error, or redirect is allowed.
- Dataset IDs are `wk1_` plus SHA-256 of a JSON tuple of normalized endpoint,
  tenant and native base ID (68 ASCII characters). Resolution is recomputed
  from the currently authorized catalog without an ID/ACL database. Credential
  rotation preserves IDs; endpoint or tenant changes invalidate old selections.
  Document IDs remain native IDs inside the dataset filter. Native WeKnora IDs
  accept only ASCII letters, digits, `_` and `-`, up to 256 characters.
- The same bindings apply to catalog, primary execution and subagents. Agent
  restrictions match the **current executor**, not the parent assistant.
  Restored scopes are re-authorized against current upstream permissions.

API calls are asynchronous, use a bounded timeout and 4 MiB response limit,
and suppress upstream bodies in errors. A response exceeding 100 hits fails;
at most 100 hits are admitted per tool call before core applies its text budget. Current connection secrets are redacted
from text evidence. Shared source formatting and output budgets remain in core.

## Verification

Offline regression tests from the repository root:

```bash
uv run --project backend --no-sync python -m pytest \
  backend/tests/test_weknora_extension.py -q
```

The tests cover connection isolation, filters without widening, missing/denied
resources, malformed responses, package registration, real ToolNode execution,
subagent identity, shared evidence, serialization/replay and budget pruning.
Run existing generic scope-admission and frontend citation suites as well.

An opt-in, read-only live check uses an **already indexed document**. Set the key
in the environment before invoking it; do not paste keys into shell history.
From the repository root:

```bash
DEER_FLOW_RUN_LIVE_TESTS=1 \
WEKNORA_BASE_URL=https://weknora.example.com \
WEKNORA_TENANT_ID=42 \
WEKNORA_KNOWLEDGE_BASE_ID=your-base-id \
WEKNORA_DOCUMENT_ID=your-indexed-document-id \
WEKNORA_EVIDENCE_QUERY='a question matching that document' \
uv run --project backend --no-sync python -m pytest \
  backend/tests/test_weknora_extension_live.py -m live -q
```

The test expects `WEKNORA_API_KEY`, performs no upload/write operation, verifies
catalog → selected document → retrieval → actual ToolNode → shared source/replay,
subagent forwarding and evidence pruning, and requires attributable results.
It supplies a deterministic tool call rather than invoking a generative model. Record the deployed WeKnora version, test result and UI
smoke-test result before claiming live delivery. Do not include keys or private
retrieval text in committed validation records.

## Scope and attribution

API mapping and filter-validation design were informed by
[superbuzzy's integration branch](https://github.com/superbuzzy/deer-flow/tree/f67609f3ab54c6d243d6f0ee1f82f2253b018b33),
especially `community/weknora/{provider,documents,retrieval}.py`, and checked
against v0.8.3's `internal/handler/knowledgebase.go`, `internal/handler/session/{types,qa}.go`,
`internal/handler/knowledge.go`, `internal/types/search.go` and
`internal/middleware/auth.go`.

This package registers the current `RetrievalProvider` contract rather than
importing the older branch's provider discovery or native citation format.
Uploads, deletion, processing management, Wiki/Graph, a knowledge management
page and new DeerFlow ACL persistence remain outside the read-only delivery.
Shared-contract durable batch source forwarding retains the existing core
limitation; ordinary subagent forwarding uses the shared evidence path.
