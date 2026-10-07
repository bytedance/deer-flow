# Router contracts

Custom Agent packages are strict, versioned definition-only JSON documents.
Export explicitly projects the caller's portable `AgentConfig` fields and SOUL;
exclude `github` installation bindings, memory contents, conversations and
credentials. Import may rename locally but must remain owner-scoped and
create-only: collisions return 409, never overwrite or upsert. Ordinary creation
and import share `_persist_new_agent`, which uses `run_drained_write` so a
cancelled request still drains the owned persistence worker.

`/api/models` projects `supports_vision` from the trusted `ModelConfig` beside
the reasoning contract. The Web UI uses this flag to stop image attachments
from being silently submitted to an explicitly text-only model; keep it present
on both list and detail responses without exposing provider credentials.
