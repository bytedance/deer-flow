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

- [x] Run unchanged native Gateway lifecycle on worker instances with PostgreSQL, DB events, Redis bridge and run ownership heartbeats. Use native multi_instance gates and compatible checkpoint configuration.
- [x] Deliver signed owner/thread launch capability through outbound dispatcher to local runtime. Admit the execution run once; central queued dispatch is not an already-running duplicate run. Preserve thread operation serialization across local and remote paths.
- [x] Confirm actual model/tool execution, read events/result from another instance, and cross-instance cancellation. Stateful browser capabilities require affinity/provider handling rather than being silently removed.
- [x] Keep placement, queue and physical STOP as executor responsibilities; no independent graph loop/checkpointer/event stack.

## Task 5: Native goal and B/C dependency coordination

Files: ecs_executor/dependencies.py, native notification/goal lifecycle adapter where required; backend/tests/test_ecs_executor_bc_main.py.

- [x] Persist awaited job membership and goal identity/revision; use native goal/checkpoint as goal authority. End/yield the current execution only after state and workspace have committed.
- [x] Release only actually freed run resources. On dependency terminal event, use one native notification path and one idempotent continuation admission.
- [x] Prove C→B→C in a minimal local pool, with original goal preserved. User cancel/goal replacement stops stale continuation; repeated events cannot start competing runs. Preserve cumulative budgets and Scheduler overlap protection.

## Task 6: Integration, operations and delivery

Files: native deployment/test docs, minimal operator scripts, final migration/integration notes and relevant README/AGENTS.

- [x] Preserve user fork changes during integration; audit removal/replacement of old Fleet hooks and schema separately. No silent destructive migration.
- [ ] Produce reproducible start/stop/restart and version rollback instructions using existing Docker build/Compose conventions. Jenkins deployment resumes only when user reopens the cloud test phase.
- [ ] Record local B/C/BC evidence and unverified cloud requirements. Ask to start ECS only once local main paths and exact cross-host scripts are ready.
- [ ] After cloud phase authorization, run native baseline → B → C → combination → Jenkins/lifecycle; keep honest passed/pending evidence.

## Evidence and completion

A protocol unit test is not B acceptance; multi_instance configuration is not C scheduling; native notification alone is not dependency coordination. All tasks remain unchecked until actual evidence covers their full scope. No IMPLEMENTED marker or overall completion while main features are pending.

Task4 configured Scheduler slice accepted: actual authenticated once task automatically launched by native ScheduledTaskService, remote C -> ordinary MCP B -> same native goal C; 1 passed / 72.92 seconds. Same occurrence/two Runs/run_count=1, goal budget, physical drain-before-B, files and final cleanup verified. Optional trusted worker contract suppresses dispatch only; foreground native tools, manual durable queue and completion remain available. Frozen native/API regressions: 528 passed, 2 live deselected / 17.52s; root independently 5 passed / 1.95s after correcting extension PYTHONPATH. Ruff 12 Python files and diff checks passed; independent SPEC then quality PASS. Task4 browser/memory and Task6 remain unchecked. No cloud or remote operation.

Task4 native memory configuration/acceptance slice accepted: no runtime/storage/protocol changes; native DeerMem canonical shared owner facts and local per-instance FTS indexes. Initial actualmain1passed43.66s, necessary same-case delivery-assertion rerun1passed46.71s; real memory_search/get/add, hidden receipt, peer visibility/other-owner exclusion, original remote Run ownership, no NAS SQLite, successful present_files/state artifacts/HTTP body. Native loader/safe merge verified; prior focused61passed4.59s and identity27passed1.24s, final loader2passed0.95s and root2passed1.02s. Ruff/diff and independent SPEC/quality PASS. Task4 browser and Task6 remain unchecked; no cloud/remotes.

Task4 local contract accepted: native execution, configured Scheduler and native memory slices already accepted; browser final zero-model control1passed19.50s, with actual model/browser/file/delivery steps separately evidenced (original model selector not overall GREEN). Fixed-scoped native tool/Live session, strict physical closure and bounded outbound control passed independent SPEC/quality. Root independently8 focused lifecycle/physical regressions. Full final gates, fork migration/operations and cloudWSS/cgroups/NAS remain Task6; no complete-project marker.

Task6A accepted locally: content dce5d110 and reviewed two-parent cached fork integration ebda3727. All559 paths classified, unrelated behavior preserved, native0035 ancestry/data preservation and independent e0001 admission verified. SPEC/quality findings fixed with narrow constraint/CLI/collation regressions; root independently7PASS across two invocations. No user DB, cloud, model or remote mutation. Exact operations, installed image/startup, final full gates and later cloud acceptance remain Task6B; Task6 remains incomplete.

Task6 Shanghai checkpoint (2026-10-10): B ordinary MCP main passed (#24 outer parser FAILURE retained), normal native B cleanup #26 SUCCESS; repaired actual C remote bash/read_file/present_files + NAS delivery #29 SUCCESS. BC #30 FAILED: source C and B completed/physical STOP, but native continuation could not read root-owned 0700/0600 publication and subsequently reached GraphRecursionError. Actual B live 500m/128MiB/non-root/network-none/PIDs64 limits were captured. A single real non-root publication regression on old core5dda reproduced the PermissionError (RED); reviewed staged-output mode fix is applied to source, immutable derivative build/GREEN and new BC trial remain pending. Admission is drained; failed run/task/goal history is retained. Full browser/WSS, lifecycle/rollback, final cloud suites and a coherent fresh cold-start bundle/pins remain pending. Task6 is not complete.


Task6 Shanghai main checkpoint (2026-10-10): #32 immutable publication derivative a216 (base5dda/patchbdd) passed the two focused cloud regressions; #33 transfer and #34 owned role refresh succeeded. Genuine installed BC #35 completed two successful native Runs, one B attempt and three physically stopped same-node jobs with automatic delivered notification, preserved goal/budget and shared NAS/API file delivery. #35 Jenkins wrapper remains FAILURE because terminal notification_run_id is a cleared lease, not persistent continuation linkage. #36 read-only proof SUCCESS verified the same trial via dependency_wait.continuation_run_id and native idempotency key; no model rerun or SQL state mutation. Root independently verified live B cgroups (500m/128MiB/PID64/networknone/nonroot) and final drained/idle state. B26 cleanup and C29 delivery remain accepted; #30 failed trial is preserved. Task6 remains unchecked: browser/WSS, lifecycle/rollback, final gates, Ruff cleanup and coherent fresh cold-start bundle/pins are pending. See docs/ecs-native-shanghai-resume-2026-10-10.md for exact identities and receipt SHA.


Task6 installed lifecycle checkpoint (2026-10-10): #37 failed its public Compose path preflight before any service mutation; the exact historical controller path/content guard was corrected. #38 SUCCESS verified worker installed operator CLI stop/start/restart plus controller host Compose application stop/start, keeping PG/Redis running. All nine steps preserved role/container and persistent volume IDs, terminal DB history/proof/NAS hashes, drained admission and strict TLS readiness; zero model/config/image-selection changes. Receipt SHA d4195da7183a32bbf09b320133f649c428e7b2601158ca93b2529c6dfce96dae independently verified. Controller native CLI and rollback were not exercised. Corrected future BC terminal notification assertion and static Ruff check/format for four files passed; historical installed image/script pins remain unchanged. Task6 remains unchecked for browser/WSS, rollback/reboot/final gates and coherent cold-start bundle.


### Shanghai installed browser checkpoint — 2026-10-10

#41 immutable Chromium image build and #42 transfer passed; #43 private-directory preflight failed before writes, corrected according to the installed root-owned directory contract in #44 SUCCESS. #45 native HTTP navigate/artifact GET worked but the wrapper wrongly expected PNG instead of native JPEG; original normal cleanup was verified. #46 SUCCESS completed the corrected single installed HTTP/WSS control main: JPEG delivery, strict CA/session/Origin, real URL-fragment input, no-seed reconnect with unchanged browser PID/native affinity, normal retirement and retained complete history. Root independently read receipt1bdab66…. No local Docker or model reruns occurred.

B26/C29/BC35+36/lifecycle38 remain accepted. Next work is the compatible52ce↔a216 rollback/restoration slice, keeping PG/Redis and all DB/NAS history, then remaining recovery/final gates and coherent cold artifacts. Controller host Compose selection is distinguished from the controller CLI limitation; OS reboot/automatic bind recovery is not yet accepted. Task6 remains unchecked.


2026-10-10 operation checkpoint: native browser installed #46 SUCCESS; same-schema compatible rollback main #48 PASS (proof90448af0…). Verified worker installed selector and controller host selection, complete restoration and history/NAS/private configuration preservation with zero models. Jenkins #48 terminal SUCCESS and independent post ALREADY_RESTORED_VERIFIED are confirmed; final frozen-source full backend/blocking-I/O gates are pending. OS reboot and database time rollback are outside this accepted slice.


2026-10-10 final-gate repair checkpoint: #54 diagnosed four CI Git/HEAD fixture failures and one missing runtime MIME table; #55 built CI-only Git/media-types image1e10. #56 existing artifact-router plus four benchmark regressions passed (107 passed, one warning, 17.32s), independently verified receipt375d935c… and exact cleanup. #53 UTF-8 existing-file regression remains 104 passed/3 skipped. No cases or model trials added. New coherent frozen source and the complete existing backend/blocking-I/O gates are pending; installed52ce still predates UTF-8/media-types corrections. Synthetic fixture HEAD is never the actual feature HEAD. Task6 remains unchecked.


2026-10-10 #57 coherent-source gate: sourceedc79/archive2d405 verified; Ruff passed, shard1 timeout906.124s with actual CI dependency/transport failures and two existing test-contract defects. Own #57 stopped normally after shard2 started to avoid repeating the known invalid environment; root verified ABORTED/exact cleanup, no full receipt or backend acceptance. Narrow existing-test repairs preserve stage/default/shutdown/privacy assertions; Ruff passed, focused runtime checks pending. CI-only make and test subprocess transport repair precede another full suite; no cases added. Installed52ce has two Python byte differences (publication AST unchanged, UTF-8 repair) and README versus the frozen 917-file runtime manifest; production MIME/source image and coherent delivery remain pending. Task6 remains unchecked. Exact evidence is in the resume checkpoint.


Task6 completed 2026-10-10: frozen sourcec6af/archivee404/manifest33078 and honest composite838e accepted; production #65 (e84, UID1000/917/MIME/noGitmake), export66, dual-host transfer67, and installed recovery69 SUCCESS. Original68 FAILURE retained and diagnosed as stale static Nginx upstream after controller recreation; recovery validated historical44 history and unchanged PGRedisUIproxy, nginx-t/reload, worker-only original refresh and final TLS/owner/drain/metadata/cgroup proof. No accepted test/model reruns. Worker installed CLI/controller host Compose, manual NAS bind recovery and same-schema rollback are accepted scope; controller installed CLI, OS automatic NAS reboot and DB time rollback are not claimed. Coherent acceptance/deployment/release documents updated. Remote Git publication stays paused. Recovery receipt 72e3327ecc4fd677dc621cc9bca5b4d41fef314e519f5afe71afbc51d71e6206.
