# Router contracts

The MCP task list accepts optional `TaskStatus` and `active_only` query filters.
Pass both to the repository before its limit; preserve `threads:read`, owner
checks, current-thread incarnation scoping, and the unfiltered array response.

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

Custom-skill edit, delete and rollback hold the owning root's process mutex and
`.custom.mutation.lock` sidecar across predecessor read, storage mutation and
history append. Peer Gateway processes sharing that root must use this same
critical section to preserve history ordering. Keep the sidecar distinct from
the nested projection lock, retain it across requests, and acquire/release both
off-loop inside the drained worker. Unrelated users retain independent locks;
external filesystem writers do not participate in this history guarantee.

### Saved native batch reports

`subagent_batches.get_batch_item_result` reuses `threads:read` owner admission
and `_owned_batch`. It reads one immutable submission position (0–99999), checks
the returned position and projects through `deerflow.subagents.batch_results`
off the event loop. Repository availability is sufficient: worker shutdown does
not remove historical read access. JSONL export and compact item paging stay
independent; never expose raw result artifacts, prompts, leases or execution specs
through this selected-report response. Real SQLite HTTP admission and denied
owner/permission regressions live in `tests/test_batch_results_http.py`.
