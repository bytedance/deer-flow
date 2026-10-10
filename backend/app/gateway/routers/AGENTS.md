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
