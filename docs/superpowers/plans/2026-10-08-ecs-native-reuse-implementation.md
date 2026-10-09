# ECS Native Reuse Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans task by task. User selected gpt-6.1-sol with medium reasoning for coding.

**Goal:** Deliver all approved B, C and C→B→C features using native DeerFlow persistence and execution, with explicit ECS scheduling/execution adapters.

**Architecture:** Official b5d921c2 is the clean implementation baseline. Native MCP Tasks tracks B; native Gateway runs C. A separate executor owns physical work/resource records; dependency coordination augments native goals and notification admission rather than introducing another Agent runtime.

**Tech Stack:** Python 3.12, native MCP interceptors/ordinary task driver, PostgreSQL, Redis, Docker, shared NAS. Cloud hosts remain stopped; deployment is deferred.

## Worktree and integration

Branch codex/ecs-native-reuse, isolated managed worktree. Old codex/shanghai-fleet-deployment remains intact. Fork integration must preserve unrelated fork changes; this branch is not a wholesale replacement of the fork. No upstream pushes.

## Task 1: Trusted native MCP submission scope

Files: create backend/packages/ecs-executor/ecs_executor/scope.py and interceptor.py; package metadata; backend/tests/test_ecs_executor_scope.py. Update README.md and backend/AGENTS.md.

- [x] Write a focused native ToolNode/OrdinaryMcpTaskDriver/interceptor test: authoritative user/thread/incarnation/run survives the real native call path without model authority fields.
- [x] Run this test RED, recording actual failure.
- [x] Implement signing and verification of bounded, expiring, argument-bound scope using an operator secret. Required claims: audience, user_id, thread_id, incarnation, run_id, operation, issued_at, expires_at, arguments_sha256. HTTP header is dedicated and reserved; strip/replace any case-insensitive preexisting instance. Never put secret/signature in tool arguments or logs.
- [x] Implement build_execution_scope_interceptor through native mcpInterceptors builder. Only configured submit tools require runtime; background status/cancel pass through and rely on saved remote scope plus per-user native credentials. No default user/thread fallback on submit.
- [x] Verify missing runtime, expired/tampered/wrong body or owner proof fails closed. A missing interceptor header is rejected by the server verification API, even if native builder loading logged an error.
- [x] Run focused tests and native context/ordinary driver regressions with actual new-worktree imports; format with backend/ruff.toml.
- [x] SPEC then quality review and commit only reviewed files. This proves the scope bridge, not complete B execution.

## Task 2: B ordinary MCP execution service

Files: ecs_executor/mcp_server.py, job_store.py, jobs.py, worker.py; backend/tests/test_ecs_executor_b_main.py; examples/ecs-native/extensions_config.example.json.

- [x] Bind native user_auth owner to signed submit claims; discovery credentials authorize discovery only. Store owner/thread/incarnation/run with opaque job ID. Do not require native local tracking IDs or direct mcp_tasks table access.
- [x] Expose submit/status/cancel structuredContent using the ordinary-tools contract. Native McpTaskService remains unchanged. Pending physical cancellation returns retryable MCP error until terminal STOP proof, never false cancelled.
- [x] Implement durable queued execution and profile-authorized Docker CPU/memory/network/user limits, output acceptance and restart reconciliation. Port useful old worker/STOP components after checking their dependencies, avoiding old staged-tracking handshake.
- [x] Drive a real local Docker job through ordinary task tracking, including result artifact; then check cancellation and one restart. Add cases only for observed risks. Persist submission idempotency and indeterminate outcomes before allowing retry.

## Task 3: Shared ECS scheduling and outbound transport

Files: ecs_executor/nodes.py, scheduling.py, dispatch.py and private migrations; backend/tests/test_ecs_executor_dispatch_main.py.

- [x] Register fixed nodes, health/drain state and node-scoped credentials. Claim/renew/report remain worker outbound. Store one resource ledger for both kinds, subtract resident Gateway overhead.
- [x] Admit B/C through one queue/profile budget. Failed/unknown attempts retain reservations until physical reconciliation. Persist handoff and idempotency before contacting execution.
- [x] Validate one local multi-process contention path and minimum-pool capacity reuse. Avoid a broad fault matrix.

## Task 4: C native Gateway execution adapter

Files: ecs_executor/agent_dispatch.py, minimal native internal admission adapter only if existing contracts are insufficient; examples/ecs-native/config examples; backend/tests/test_ecs_executor_c_main.py.

- [ ] Run unchanged native Gateway lifecycle on worker instances with PostgreSQL, DB events, Redis bridge and run ownership heartbeats. Use native multi_instance gates and compatible checkpoint configuration.
- [ ] Deliver signed owner/thread launch capability through outbound dispatcher to local runtime. Admit the execution run once; central queued dispatch is not an already-running duplicate run. Preserve thread operation serialization across local and remote paths.
- [ ] Confirm actual model/tool execution, read events/result from another instance, and cross-instance cancellation. Stateful browser capabilities require affinity/provider handling rather than being silently removed.
- [ ] Keep placement, queue and physical STOP as executor responsibilities; no independent graph loop/checkpointer/event stack.

## Task 5: Native goal and B/C dependency coordination

Files: ecs_executor/dependencies.py, native notification/goal lifecycle adapter where required; backend/tests/test_ecs_executor_bc_main.py.

- [x] Persist awaited job membership and goal identity/revision; use native goal/checkpoint as goal authority. End/yield the current execution only after state and workspace have committed.
- [x] Release only actually freed run resources. On dependency terminal event, use one native notification path and one idempotent continuation admission.
- [x] Prove C→B→C in a minimal local pool, with original goal preserved. User cancel/goal replacement stops stale continuation; repeated events cannot start competing runs. Preserve cumulative budgets and Scheduler overlap protection.

## Task 6: Integration, operations and delivery

Files: native deployment/test docs, minimal operator scripts, final migration/integration notes and relevant README/AGENTS.

- [ ] Preserve user fork changes during integration; audit removal/replacement of old Fleet hooks and schema separately. No silent destructive migration.
- [ ] Produce reproducible start/stop/restart and version rollback instructions using existing Docker build/Compose conventions. Jenkins deployment resumes only when user reopens the cloud test phase.
- [ ] Record local B/C/BC evidence and unverified cloud requirements. Ask to start ECS only once local main paths and exact cross-host scripts are ready.
- [ ] After cloud phase authorization, run native baseline → B → C → combination → Jenkins/lifecycle; keep honest passed/pending evidence.

## Evidence and completion

A protocol unit test is not B acceptance; multi_instance configuration is not C scheduling; native notification alone is not dependency coordination. All tasks remain unchecked until actual evidence covers their full scope. No IMPLEMENTED marker or overall completion while main features are pending.
