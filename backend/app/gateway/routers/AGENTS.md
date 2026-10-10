# Router contracts

Custom Agent packages are strict, versioned definition-only JSON documents.
Export explicitly projects the caller's portable `AgentConfig` fields and SOUL;
exclude `github` installation bindings, memory contents, conversations and
credentials. Import may rename locally but must remain owner-scoped and
create-only: collisions return 409, never overwrite or upsert. Ordinary creation
and import share `_persist_new_agent`, which uses `run_drained_write` so a
cancelled request still drains the owned persistence worker.

Committed MCP reconciliation failures are logged once by
`fail_mcp_reconciliation`, with only the underlying exception type.
`_run_drained_mcp_apply` passes `_McpCommittedReconciliationError` as an expected
error to `run_drained_write` to avoid a duplicate diagnostic. It still drains
retired-pool cleanup outside the config locks and reports the fixed-detail 500.
