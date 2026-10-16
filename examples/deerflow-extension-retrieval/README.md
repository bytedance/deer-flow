# Synthetic retrieval with plugin tool artifacts

This is a small, read-only example for `ModelTool(response_format="content_and_artifact")`.
It searches two fixed **synthetic** documents in memory. It makes no network or
model requests, reads no user files, and has no UI, database, ingestion, or write
operations. All users see the same demonstration corpus; it is not a private
knowledge base or a factual company source.

The package imports only Python's standard library and `deerflow-extension-api`
0.2.6 or newer. It does not import private DeerFlow harness modules.

## Enable explicitly

Install this trusted local package using the normal extension workflow:

```sh
deerflow extensions install /absolute/path/to/examples/deerflow-extension-retrieval
```

The contribution is disabled by default. To enable it, set the installed entry's
configuration to `enabled: true` and restart the Gateway. For a source package
already on the Python path, the equivalent deployment entry is:

```yaml
plugins:
  - use: deerflow_extension_retrieval:install
    config:
      enabled: true
```

The registered model tool performs case-insensitive literal matching. For
example, the query `release` returns the synthetic release note. Empty queries
and additional arguments are rejected by the tool schema.

## What the example proves

The handler returns `PluginToolResult`: readable text is model-visible, while a
JSON artifact contains `schema`, `synthetic`, and structured `matches`. The host
assigns the tool name and call ID. The artifact contains no secret information;
artifacts are retained in state and API output, not a secret-storage boundary.

The integration test loads this package through `load_extensions`, dispatches
the real `ToolNode` with `ToolOutputBudgetMiddleware`, saves to SQLite, closes
and reopens the saver, reads through `CheckpointStateAccessor`, and serializes
the restored state. A later turn also checks the standard model-message
conversion receives text rather than the artifact. Both full and delta
checkpoint modes are covered, including content truncation.

The artifact is generic example metadata. It does **not** claim to be a native
RAGFlow citation, enable citation cards, or participate in source-aware budget
pruning or subagent source forwarding. Generic artifacts can outlive truncated
content; adding an artifact does not establish evidence authority.

From an existing DeerFlow backend development environment with API 0.2.6:

```sh
uv run pytest tests/test_retrieval_plugin_artifacts.py -q
```
