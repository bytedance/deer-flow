# Structured artifact retrieval example

This opt-in full-stack plugin demonstrates the `ModelTool` artifact channel. The
read-only `retrieve_sources` tool returns a short sentence to the model while
keeping source IDs and excerpts in `ToolMessage.artifact`:

```python
PluginToolResult(
    "Found 1 source for the requested topic.",
    {"query": query, "sources": [{"id": "deerflow-guide", "excerpt": "..."}]},
)
```

The catalog is intentionally deterministic and in-memory so the example needs no
provider, database or credentials. Replace the handler's retrieval body with a
trusted provider while retaining the same bounded result contract. The artifact is
host data for evidence consumers; it is not automatically a citation and does not
grant permission to read another user's resources.

Install the package through the normal extension manager, enable it, and restart
Gateway. Ask the lead agent to call `retrieve_sources`; the ordinary tool message
contains the concise summary and the host retains the structured source records.
