# LightRAG entity relation retrieval

Optional read-only plugin for #6269's **new Phase 1**. Provides document retrieval
and entity relations through the existing tool configuration, scope admission,
shared evidence formatter and citation readers. No management or frontend plugin
is required. Requires a host with the new `relations_search` capability.

The response mapping follows LightRAG v1.5.7 commit
[`28ff1b05f2ac3f3e6fa14dd2cd33656579bd0c9c`](https://github.com/HKUDS/LightRAG/blob/28ff1b05f2ac3f3e6fa14dd2cd33656579bd0c9c/lightrag/utils.py)
(`convert_to_user_format`), using `POST /query/data` in `hybrid` mode.

Install from the repository root:

```sh
make extension-install SOURCE=/absolute/path/to/examples/deerflow-extension-lightrag
```

Merge into the installed plugin configuration and restart Gateway:

```yaml
plugins:
  - use: deerflow_extension_lightrag:install
    enabled: true
    required: true
    config:
      base_url: https://lightrag.example.com
      api_key_env: LIGHTRAG_API_KEY
      user_ids: ["YOUR_DEERFLOW_USER_ID"]
      # Optional exact current executors, including allowed subagents:
      agent_names: ["lead_agent", "researcher"]
      top_k: 20
      timeout: 30
knowledge_base:
  enabled: true
tool_groups:
  - name: knowledge
tools:
  - name: entity_relations_search
    group: knowledge
    use: deerflow.knowledge.tools:entity_relations_search_tool
    provider: lightrag-relations
  # Optional document search using the same authorized connection:
  - name: knowledge_search
    group: knowledge
    use: deerflow.knowledge.tools:knowledge_search_tool
    provider: lightrag-relations
```

Set `LIGHTRAG_API_KEY` in the Gateway environment. This plugin requires an explicit
credential and exact user binding; it never falls back to an anonymous or more
privileged connection. Bound users share the credential's upstream visibility;
this is not upstream user impersonation. Upstream authorization remains final.

Remove a tool entry to disable that operation. The legacy built-in LightRAG
document tool remains compatible and does not require this plugin.

## Evidence and limits

- Returns upstream entities and **one-edge paths** (`src_id`, `tgt_id`, description).
  It does not compute multi-hop paths, infer new edges, or claim graph completeness.
- Each edge's `source_id` is split using LightRAG's `<SEP>` delimiter and joined to
  retrieved `chunks[].chunk_id`. Only those actual chunks can receive document
  citations, using their file title or the returned reference mapping.
- Edge descriptions and entity summaries remain unattributed graph facts. A
  returned edge without matching retrieved chunks is explicitly marked as lacking
  document evidence. Merely sharing `file_path` does not establish evidence.
- Uses the existing `KnowledgeSource` envelope unchanged. Graph descriptions and
  document excerpts are separate hits, so a graph summary cannot become a quotation.
- Scope is limited to `all` (the bound workspace) or `disabled`. Dataset/document
  selections are rejected before requests; no unrestricted retry. Combining
  different registered providers also disables the shared selector because their
  resource IDs have no common namespace.
- Requests do not follow redirects, have a timeout and a 4 MiB response cap.
  Core bounds displayed results and citations; returned graphs are partial views.

Offline synthetic tests cover HTTP requests, permissions, evidence joins,
malformed payloads, secret redaction, combinations, delegation, replay and budgets.
A real OrbStack deployment with bge-m3 and GLM-5.3 also passed provider and
three-tool agent checks; see the [validation record](VALIDATION.md) for versions,
reproduction steps and limits. Offline passes alone are not live acceptance.
Deployment verification must inspect both relation facts and original evidence.

Shared graph evidence chunks are emitted once per returned chunk ID, before the
first referencing edge. Every edge names its evidence result positions; prefix
truncation therefore cannot leave a retained edge pointing to omitted evidence.
