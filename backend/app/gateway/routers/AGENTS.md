# Router contracts

Custom Agent packages are strict, versioned definition-only JSON documents.
Export explicitly projects the caller's portable `AgentConfig` fields and SOUL;
exclude `github` installation bindings, memory contents, conversations and
credentials. Import may rename locally but must remain owner-scoped and
create-only: collisions return 409, never overwrite or upsert. Ordinary creation
and import share `_persist_new_agent`, which uses `run_drained_write` so a
cancelled request still drains the owned persistence worker.

Custom-skill edit, delete and rollback hold the owning root's process mutex and
`.custom.mutation.lock` sidecar across predecessor read, storage mutation and
history append. Peer Gateway processes sharing that root must use this same
critical section to preserve history ordering. Keep the sidecar distinct from
the nested projection lock, retain it across requests, and acquire/release both
off-loop inside the drained worker. Unrelated users retain independent locks;
external filesystem writers do not participate in this history guarantee.
