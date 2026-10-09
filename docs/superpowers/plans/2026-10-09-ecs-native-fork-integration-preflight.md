# Native fork integration preflight (2026-10-09)

Preflight started read-only; Task6A now prepares reviewed content and additive
schema compatibility against implementation HEAD 5164c6fc. Tasks1-5, including
browser local contracts, were accepted at their recorded scopes. No history merge,
user database operation, cloud operation, fetch or push has been performed.
Task6A's owned ephemeral PostgreSQL ancestry main passed fresh/native0034/Fleet0022
upgrade, row preservation and activation quarantine; this is not cloud acceptance.
See `docs/ecs-native-fork-integration.md` for current disposition/evidence.

## Local references and preserved history

User GitHub fork/main: 96bacf4f42ee1ae24ab988cc369e0720c65f0bd5. Gitee/master: a816a744fa8ded80a638c1262384cd2f72124751. These are local cached references, not newly verified remote heads. Shared ancestor with official source: c35022e18bead8aa35020f2ffa31f28dd2ac4622. origin belongs to the official company repository and is never the push target.

Retain fork-only migration IDs and parents: 0018_thread_execution_bindings -> 0019_scheduled_execution -> 0022_fleet_main_merge. The final revision merges 0019_scheduled_execution with 0019_thread_incarnations. Current native head is 0034_run_event_seq_watermark. A compatible migration graph must reach one integrated head from fresh schema, official head and old Fleet head; do not stamp an old database as if new migrations had run.

Legacy table thread_execution_bindings and scheduled_tasks.execution contain prior placement/workspace intentions. Preserve original rows/JSON for explicit disposition and rollback. New runtime must not silently treat legacy intent as a new job, execute it locally or allow old and new dispatchers together. Inventory existing active tasks, occurrences and runs before activation; drain or quarantine unresolved old execution and document the exact mapping. No disposition has been applied to user data. Native activation now fails closed while legacy intent remains.

User Docker development commit 0aee70969189d92083f4d71ede82f5631c320347 changes .env.example, README.md and docs/DOCKER_DEV.md. Preserve and adapt its database wiring explanation to current native topology. Review other user-fork changes separately from retired Fleet implementations; preserve the user preference about disabled GitHub Actions.

## Independent execution schema

The ECS ledger has ecs_execution_jobs, ecs_execution_nodes and ecs_native_affinities. Task6A replaces production MetaData.create_all with read-only compatibility admission and an independent e0001_execution_ledger Alembic upgrade. JobStore.initialize remains an explicit Python local/test helper executing that versioned path. Task6A supplies the independent versioned path and non-mutating compatibility checks; Task6B must validate deployed operational compatibility. Native runs/MCP/schedules retain native migration ownership.

Native migrations already support operator-declared extension table_prefix filtering to avoid dropping independently owned tables during autogenerate. ECS currently has no packaged extension entry point. Do not pretend a prefix declaration alone makes a portable runtime plugin; decide documented independent database/migration isolation or explicit supported declaration before production use. Keep required native hooks visible in the user fork.

## Remaining acceptance

- Integrate cached user-fork history locally with explicit retired/replaced/retained file and behavior mapping, then preserve any newer remote user changes when the publishing phase resumes.
- Fresh, official-head and old-Fleet-head database upgrade tests must execute real migration ancestry and preserve representative native and legacy rows. No destructive downgrade; rollback needs drained processes and a coherent database/NAS backup.
- Reproducible start/stop/restart/health/version rollback scripts must supervise actual Gateway 500m/1GiB and AIO 1CPU/1GiB cgroups, native outbound workers and the shared ledger. Browser control needs its required WebSocket ingress proxy path; worker gains no inbound port.
- Run final locked backend and blocking-I/O gates once the complete local feature batch is stable. Historical Task3 gates do not cover later C/Scheduler/memory/browser changes.
- Shanghai cloud NAS locks, cross-host transport, cgroups, Jenkins and restart/rollback remain deferred until local scripts are ready and the user reopens the stopped resources.

This preflight does not satisfy Task6 and does not mark the objective complete.
