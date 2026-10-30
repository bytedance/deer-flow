# Synthetic read-only knowledge provider

This independently packaged, offline example registers a `RetrievalProvider`
with optional catalog, documents and scope filtering. It has one invented
document and no external API, management service, or browser bundle. The corpus
is deliberately public to all users; production adapters must map the host
identity in `KnowledgeRequestContext` to provider permissions on every request.

Install it from an absolute local path using DeerFlow's extension manager, then
configure the existing `knowledge_search` entry and restart Gateway:

```yaml
plugins:
  - use: deerflow_extension_knowledge:install
    enabled: true
    required: true

knowledge_base:
  enabled: true
  scope_selection_enabled: true

tool_groups:
  - name: knowledge

tools:
  - name: knowledge_search
    group: knowledge
    use: deerflow.knowledge.tools:knowledge_search_tool
    provider: synthetic-example
```

Merge these entries with your existing configuration. The provider name is an
operator-selected registry key, never a user-supplied module path. Select
**Synthetic guides**, optionally select **Synthetic knowledge note**, and ask
the Agent to search for `Cedar`. The returned source is captured evidence of
the invented example text, with no fabricated page or URL.

Unknown datasets or documents fail rather than widening scope. The core
creates the source artifact, applies evidence validation and budgets, and
preserves the existing message/runtime scope boundary. The separate
`deerflow-extension-retrieval` example continues to demonstrate
`ModelTool(response_format="content_and_artifact")` and `PluginToolResult`;
this example consumes the same public source semantics through the stable
`knowledge_search` entry point.
