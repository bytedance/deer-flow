# Native reuse implementation audit notes

## B: durable tracking before execution

Native McpTaskService submits remotely, then SQL repository create commits the tracking row. The poller claims rows in a separate session and commits its lease before calling get_status. Therefore the first normal native poll cannot precede tracking commit, although it may precede submission refresh/return.

The executor can persist submit as staged and activate only on a signed background status call. Workers consume queued rows only. Activation, cancellation and staging expiry must serialize in one transaction; terminal rows never reactivate. Require HTTP plus native user_auth so the background caller installs the persisted owner. A signed status is Gateway-origin evidence under this configured chain, not a general database commit certificate.

Lost submit responses leave staged jobs which expire without execution. Cancellation compensation can arrive before tracking exists and must never activate work. If commit succeeded but refresh failed, a poll may already have activated the job, so cancellation requires actual STOP evidence. Submission idempotency and uncertain acknowledgements still require explicit implementation; do not import old Fleet tracking-ID reuse blindly.

## C: native admission and cleanup

Use native app.gateway.services.start_run exactly once, with a stable dispatch idempotency key and immutable envelope. Outbound worker delivery resolves server-owned owner/thread binding before creating an internal local request. An extension service currently lacks public run admission/app/cancel capabilities; a trusted local route or a minimal host capability is needed. Custom HTTP admission also needs runs:create permission enforcement.

Native terminal status, extension task-stop, and SSE end occur before journal/sandbox/reference cleanup. Resource release cannot use those events as physical STOP receipts. Await attached native task completion and account separately for external sandbox/process cleanup; restart-safe receipts require an owner-fenced durable acknowledgment. Keep resident Gateway resources reserved even after a run ends.

## Goal continuation

Native thread checkpoint GoalState remains goal authority. Native MCP notifications already re-enter start_run with durable delivery idempotency and busy-thread retries. Extend dependency membership and admission validation around that path; do not add another goal evaluator or competing Agent loop.

These are verified integration findings, not acceptance evidence for complete B/C/BC. Cloud deployment remains deferred.

## Shared host requirements verified from the native source

The user repository class retains the name SQLiteUserRepository but receives the shared async session factory and supports PostgreSQL. User authentication does not need a second executor user database. Instances require the same JWT secret and native authorization checks; possession of a node credential never grants arbitrary user/thread authority.

Native multi-instance startup requires PostgreSQL, DB run events, ownership heartbeats and Redis stream bridge. Scheduler needs its own multi_instance flag if enabled. Stateful native browser tools are currently rejected by the gate even with a fixed dispatcher affinity. They are commented out in config.example.yaml. For an operator who enables interactive browsing, the supported existing integration seam is authenticated HTTP/SSE browser MCP with explicit persistent session identity or thread-to-node affinity and defined restart behavior. This preserves interactive tool capability but does not automatically expose the native Browser Live UI; that UI would require an additional provider/owner routing integration. Do not claim all browser transports are interchangeable.

AIO Docker is a candidate native shell sandbox for fixed ECS nodes: each worker owns local Docker; Redis coordinates sandbox ownership; shared paths and thread_data_mounts must match on the Gateway and sandbox side. Warm processes and browser state remain node-local and are not migrated by NAS. Local provider with allow_host_bash=false does not satisfy shell execution; do not silently use that setting while claiming full bash support.

DeerMem body/manifest and skill/config projections already use file locks. Keep its derived SQLite FTS5/WAL retrieval index on each instance's local disk using an absolute retrieval_index_path, while sharing only the authoritative memory files. NAS flock, atomic rename and cross-node refresh still need later cross-host acceptance.

## Fork preservation audit

Local refs checked before integration: fork/main is 96bacf4f and Gitee uses gitee/master, not gitee/main. The common ancestor with the official baseline is c35022e1. Both sides have substantial changes; the new branch must not be pushed as a force replacement of the fork. Review fork-only core changes separately from Fleet adapters, retain unrelated fixes, and preserve old migration/data history. Current implementation remains on codex/ecs-native-reuse; no remote update is implied by its local commits.

## Local model preflight (2026-10-08)

Using the new checkout's native PatchedChatDeepSeek with the existing main checkout's private configuration, one request with max_tokens=8 returned READY successfully. Configured model alias: deepseek-chat; returned provider model: deepseek-flash. Secret values were not printed or copied into this repository. This is only provider connectivity evidence; it is not C Agent/model/tool/dispatch acceptance.

## Preserved timeout preference

The previous implementation's FleetConfig.lease_seconds defaults to 120 seconds, and delivery notes retain a cumulative 120-second cleanup/quarantine safety budget. Preserve the user's accepted 120-second lease/cleanup allowance when adding the shared pool; do not shorten physical-stop safety waits merely to make local fault tests faster. This is separate from configurable per-program execution deadlines and fresh per-call signature lifetimes.

## B file delivery implementation boundary

A log JSON artifact alone does not satisfy the original shared-input/output requirement. The B main additionally needs an owner/thread-scoped immutable input snapshot, persistent isolated outputs, bounded regular-file collection and manifest integrity, plus publication through the native user/thread artifact path. Native metadata owner/incarnation remains authoritative during publication; no duplicate thread table or access to native mcp_tasks is needed. Keep private results after stale-thread rejection without replaying computation. A remote service Bearer URL is not a substitute for the native browser/session-authorized file entry.

## Task 2 review and verification (2026-10-09)

Independent SPEC review passed after a combined inline/reference input-count admission fix. Root independently reproduced the focused scope/B suite: 17 passed, 1 explicit Docker opt-in skipped. Actual TCP/PostgreSQL/Docker execution also passed after that guard, including immutable native upload snapshots, restart without replay, native artifact ownership and physical cancellation. Quality review identified a real normal-terminal Docker-object cleanup leak; durable cleanup_pending and an independent terminal cleanup sweep fixed it. The lifecycle regression proves failed removal and SQL/worker restart preserve results without start replay. Independent quality re-review passed. Latest locked-environment focused suite: 18 passed, 1 explicit opt-in skipped; latest actual TCP/PostgreSQL/Docker main: 1 passed in 16.48 seconds, including automatic completed-container removal before fixture cleanup. Task 2 is now verified; local implementation commit ddf85787.

The first repository-wide offline attempt reused the old checkout virtual environment and a temporary uv wrapper. Subprocess tests deliberately changed PYTHONPATH, selecting the old extension-api 0.2.0; the wrapper also rejected uv --version/lock. That run is not valid regression evidence for this branch. A dedicated backend/.venv was then created with uv sync --locked --extra postgres --extra redis. Genuine make test completed with exit 0: all four shards passed (26,761 passed, 411 skipped; slowest shard 303.55 seconds); genuine make test-blocking-io passed 229 tests (20.19 seconds). No application credentials or database URLs are recorded here.

## C admission seam inspection after B acceptance (2026-10-09)

The current Gateway start_run admits one durable native RunRecord via create_or_reject and immediately attaches run_after_metadata; the router uses that record for existing SSE and run-location URLs. Native try_start requires an entry in the executing manager's local _runs registry. RunManager.get can hydrate a peer row but does not adopt or register it as a local executable record. Existing expired-owner takeover is failure/cancellation reconciliation, not a healthy pending-run handoff. Consequently, simply calling start_run again on the remote worker with the same idempotency key returns the reused record without attaching its worker; using a different key creates a second run and violates the required one-admission path.

Task 4 must resolve this explicit seam while preserving the existing HTTP/SSE lifecycle: either add a narrow trusted pending-admission handoff/adoption hook, or prove another approach that gives durable queue/cancel/thread serialization and exactly one native execution run. A standalone new dispatch endpoint alone does not prove transparent existing frontend behavior. Native worker ownership, pending cancellation, same-thread active-operation uniqueness and post-cleanup settlement must remain authoritative; executor lease expiry never substitutes for physical STOP. No implementation approach is declared proven by this inspection.

A disposable in-memory two-RunManager probe confirmed the seam: the peer can read the exact native run record, but peer.try_start raises RunStartupError because hydration does not register an executable local record. The probe used no model, cloud host or production database. This is evidence of a missing healthy handoff capability, not C acceptance.

## Newly observed native filename compatibility gap

The B relative_file helper currently permits ASCII alphanumeric/underscore/dot/hyphen only. A direct current-source probe rejected both uploads/报告.xlsx and outputs/sales report.csv, although these are ordinary native upload/output names. This is a compatibility fix still required before final delivery: retain relative-path, component, control-character and no-follow protections while accepting native Unicode/space filenames. Do not widen unsafe path traversal or add a broad filename matrix. The Task 3 implementer is keeping the pool main-path work separate; root must schedule the focused fix before final B/C/BC acceptance.

## Task 3 accepted local evidence

Shared dispatch implementation 5ce7d9f5 passed independent SPEC and quality review, the latest actual PostgreSQL/TCP/two-worker/native-task/Docker main, and genuine locked repository gates (26,762 offline passed / 412 skipped, 229 blocking-I/O passed). Reservations include all B/C kinds, recovery is kind-isolated, unknown work remains reserved, and poll queries aggregate/filter before loading large payloads. This does not establish native C execution, cross-host NAS or cloud deployment.

For Task 4 resource release: current AioSandboxProvider.release explicitly parks healthy sandboxes in a warm pool; replicas is a soft cap for active containers. Native run worker releases its execution lease after stream finalization, but neither event proves the warm container stopped. Charge a bounded warm sandbox allocation as resident overhead (with matching active-run/replica limits), or retain its reservation until actual destruction is confirmed. Do not release its CPU/memory merely because record.task settled. Local image inventory contains no AIO sandbox image; BoxLite needs host virtualization and must not be assumed supported on the economic ECS instances. Existing old Fleet runner images are not native C acceptance.

## Native filename follow-up verified

Native Unicode and space filenames now survive immutable snapshots, input preparation, output collection, publication/replay and the existing artifact owner route. Relative paths are bounded to 512 UTF-8 bytes total and 255 per component; traversal, controls, backslashes and invalid Unicode are rejected. Publication writes output names relative to a no-follow files directory fd. Review exposed prefix/host path-limit boundaries; the final existing regression verifies an actual 511-byte path and rejects oversized input. Focused suite: 18 passed, 1 explicit Docker opt-in skip; root independently reran the final native file-chain regression (1 passed in 1.64s). SPEC and quality re-reviews PASS. No new full gate or Docker acceptance is claimed for this small follow-up. Task 4 remains pending.

## Fork migration integration preflight (read-only)

Current local fork/main is 96bacf4f42ee1ae24ab988cc369e0720c65f0bd5; gitee/master is a816a744fa8ded80a638c1262384cd2f72124751. No remote fetch or mutation was performed. The fork preserves 0018_thread_execution_bindings (parent 0017_personal_access_tokens), 0019_scheduled_execution (parent 0018_thread_execution_bindings), and the no-DDL merge revision 0022_fleet_main_merge joining 0019_scheduled_execution with 0019_thread_incarnations. Its downgrade explicitly refuses an unplanned Fleet rollback. The official implementation baseline instead continues from 0019_thread_incarnations through 0022_scheduled_occurrence_seq and later native migrations. Task 6 must retain the old revision identifiers and add a compatible merge/upgrade path; copying only the new native migration tree would strand existing fork databases stamped at the Fleet head. The preserved old execution routing table and scheduled_tasks.execution column need an explicit legacy-data disposition, not silent deletion. This inspection is a required integration constraint, not completed integration or migration acceptance.

## Task 4a native pending handoff seam verified

One durable native pending Run can now transfer through owner/status/thread/user CAS and be adopted as a real local executing record. Startup checks owner and pending cancellation; handoff/adoption require native heartbeats and a finite lease. The former manager detaches its local registry and peer reads use SQL. Gateway start_run delegates optional placement to an operator-installed admission host, preserving default native task attachment. Pre-handoff host failures fail the pending admission; former owners cannot finalize after handoff or ambiguous acknowledgements. Relevant native manager/repository/services plus focused C regressions: 434 passed in 10.85 seconds. Root independently reran both C seam tests: 2 passed in 1.01 seconds. Independent SPEC and quality reviews PASS. This is only Task 4a, not full C: outbound C launch, durable queue recovery, canonical native payload adoption, actual model/sandbox execution, peer events and cross-instance cancellation/physical settlement remain Task 4b. Task 4 remains unchecked; no overall completion or new whole-backend gate is claimed.

## C warm capacity guard still required

AIO replicas=1 and one C run at a time do not by themselves prove a one-container physical bound. Current AioSandboxProvider acquisition calls _evict_oldest_warm when total >= replicas, but continues to backend.create after an eviction failure/refusal; WarmPoolLifecycleMixin explicitly logs creation beyond its soft limit. A refused/failed warm destruction can therefore leave one existing warm container and create another for a different thread. The native C worker must fail closed before this allocation, or retain the unknown extra allocation and block fresh admission. The planned 1500m CPU/2048MiB resident reservation (AIO1000m/1024MiB + Gateway500m/1024MiB) is only justified once that physical bound is enforced. Source inspection is not an implemented guard or completed C acceptance.

## Task 4b first native execution evidence; acceptance still pending

The implementer reported disposable live session 69287 terminal and cleaned. Its first actual remote native Run passed peer checkpoint read, SQL worker-owner identity, native bash/read_file tool-call checks, the calculated Linux artifact, and inspected AIO Docker limits of 1 CPU/1 GiB. The later ordinary interactive Run used the durable thread affinity and the same warm container, but its expected exported shell marker was empty, so the case stopped before cancellation/physical STOP acceptance. This is partial functional evidence, not a passing whole C case, independent final review, Linux Gateway cgroup proof, or Task 4 completion. Investigate the actual command/session semantics before treating the marker assertion as an implementation defect.

Source inspection now shows an opt-in hard AIO capacity guard, strict Docker running-count check, and a separate native-node flock (distinct from the B daemon node lock). Unknown Docker inspect state raises rather than proving STOP. These changes remain uncommitted and under validation. Successful graph completion can retain a warm sandbox continuously charged to resident resources; dynamic reservation release must not be described as destruction of that warm container.

## Native notification continuation entry inspected

The existing launch_mcp_task_notification_run creates an internally authenticated owner-scoped request with mcp_notification origin, require_existing_thread=True, multitask_strategy=reject, and task/version/attempt idempotency, then calls the same native start_run. Task 5 must bridge that entry to central durable placement when originating on a worker, preserving incarnation/goal/dependency fences and existing native notification authority. Rejecting all worker-side notification admissions or creating a parallel notification/graph loop does not satisfy C-to-B-to-C. This is a located integration seam, not implemented continuation acceptance.

## C cancellation integration findings (still pending acceptance)

Live 40461 completed the first native success and proved later interactive affinity through the same Docker container ID and a container-local /tmp file. Central durable cancellation reached the worker, but physical settlement did not finish within the fixture's original 30-second observation: native sandbox.close waits on the busy shell lock before backend destruction. The accepted cleanup observation budget is 120 seconds, but a long shell can still block close beyond that budget. The opt-in hard-capacity worker is being changed to stop physical execution under its native ownership/teardown lease before closing the client; the default provider path remains unchanged. Tracking must survive failed or unknown STOP.

Independent source inspection found LocalContainerBackend._stop_container logs CalledProcessError without raising, so backend.destroy returning is insufficient physical evidence. Strict stopped-state inspection inside the held teardown lease is required before untracking. Later worker inspection can prevent capacity release but cannot recover a prematurely discarded tracked container.

A separate concrete queue bug treated every native terminal row, including success, as cancel_requested. The fix now only propagates an explicit durable cancel_action and leaves normal terminal settlement to native task finalizers plus worker reporting. Root independently ran the normal-terminal cancellation guard and provider-unavailable STOP guard: 2 passed in 1.11 seconds.

Live 83496 terminated and cleaned after an initial native error, before the later cancellation path. Native RunResponse omits the error field, so API error=None is not evidence of an absent durable error. The next existing main run must capture SQL status/error/owner/cancel_action and bounded native checkpoint/event diagnostics before fixture cleanup if failure recurs. None of these partial runs establishes full Task 4 acceptance or Task 5 completion.

## Native C execution slice actual main verified; full Task 4 pending

After preserving the native artifact delivery gate and adding explicit present_files delivery to the same existing case, implementer live 10162 passed in 39.57 seconds. Final STOP is coalesced per owned job so cancellation polling and native task finalization await one physical proof; failed STOP remains retryable and unknown attempts retain their reservations. A final ownership_lost guard also prevents release based on a former owner's task outcome.

Root independently reproduced the final existing actual main in session 93406: exit 0, 1 passed in 43.94 seconds. The case covers real DeepSeek inference, native AIO bash/read_file/present_files delivery, the original SQL Run ID and worker owner, peer native checkpoint and Redis END, a later interactive Run on the same Docker container with container-local /tmp state, and central cancellation followed by native task finalizers and exact physical STOP before dynamic reservation release. Test-owned infrastructure was cleaned. This is local two-Gateway functional evidence; it does not prove a Linux Gateway cgroup bound or cloud operation. The existing provider-STOP ordering regression independently passed in 0.98 seconds, in addition to the two terminal/provider guards recorded above.

Fresh SPEC review of the execution slice is underway, with quality review to follow. Full Task 4 remains unchecked: native browser startup gate and live HTTP/WS affinity, memory shared-file/local-index configuration, and scheduler/worker admission capabilities still require integration. Task 5 native notification/dependency C-to-B-to-C, Task 6 fork migration/operations, and later authorized cloud acceptance also remain outstanding. A passing shell main does not narrow the accepted complete native Agent requirement.

## Execution slice fresh SPEC review findings

Fresh SPEC review rejected the current execution slice despite the passing normal main. Four concrete introduced paths are being corrected before quality review: an adopted native task loses outbound tracking if its running report fails (and failed STOP has no retry owner); redacted persisted config is incorrectly reused as execution config, dropping native request-scoped skill secrets; worker startup can orphan expired dispatch-owned queued Runs before contacting the central dispatcher; queued cancellation commits a terminal job before native Run terminalization/END, and terminal rows are then excluded from maintenance.

Root confirmed the native secret_context carrier contract and located the existing ChannelCredentialCipher/Fernet mechanism, rather than permitting plaintext credential storage or permanently disabling secret-bearing runs. Root also verified finish_dispatch_pending is an owner/pending CAS whose repeated call returns false, so durable settlement recovery must separately recognize its already-committed matching native terminal state before retrying END. Physical cleanup responsibility and adopted-task tracking must survive reporting errors, while native RunManager remains the authority for task draining and unknown resources remain reserved. Known full Agent capability and Task 5/6 work remain outstanding; no Task 4 checkbox or completion claim was changed.

## Execution SPEC fixes re-reviewed; quality review pending

The original four SPEC findings are now resolved according to the same independent reviewer. The normal existing actual model main passed again after the fix batch in live 59421: 1 passed in 49.00 seconds, with owned resources cleaned. Root independently verified reporting/secret/SQL END recovery regressions (3 passed in 3.41 seconds), the strengthened expired queued-lease/bootstrap case (1 passed in 0.98 seconds), and the retained cleanup path with the actual subprocess.TimeoutExpired type (1 passed in 3.97 seconds). The latter normalizes ordinary physical backend failures to retryable outcomes without intercepting shutdown/cancellation BaseExceptions, while preserving one native graph task and STOP responsibility. No additional model run was required for this exception-only fix. Fresh quality review of the execution slice is now underway. Full Task 4, Task 5 and Task 6 remain unverified.

## Native dependency coordination anchors inspected

TaskSubmitRequest already carries the originating native run_id, user_id, thread_id and thread_incarnation; dependency membership can therefore refer to native task records without treating model-supplied IDs as authority. Native GoalState is a TypedDict with objective, created_at, updated_at, continuation_count and cumulative limits, not a separate Goal ID entity. Native read_thread_goal/write_thread_goal remain the authority. Native external_wait is not in CONTINUABLE_GOAL_BLOCKERS (only goal_not_met_yet is), so an awaited dependency must resume through the existing task notification entry after committed goal/checkpoint and workspace state, rather than spinning a second goal evaluator loop. Scheduler overlap protection and cumulative continuation budgets remain explicit Task 5 requirements. This is read-only integration evidence, not implemented continuation behavior.

## Native C execution slice review accepted

Fresh quality review found two introduced lifecycle gaps: worker admission could race the native shutdown snapshot, and pre-adoption refusal could lose durable settlement after native terminal commit. Both are now fixed and passed targeted SPEC and same-reviewer quality re-review. Shutdown quiesces claims/adoptions before manager drain, with final synchronous attachment guards and cleanup-only observation of adopted aborts. Owned single-flight STOP and native finalizers retain client/node-lock quarantine until they unwind; bounded shutdown waits use the accepted 120-second allowance. Typed refusal persists recovery intent before native terminal CAS, preserves cancellation priority, retries END/job settlement after restart, and never releases an already-adopted or unknown owner.

Latest focused run 87520: 609 passed in 13.27 seconds. The existing actual model C main 10261 passed in 49.78 seconds, then cleaned its owned infrastructure. Root independently reran the two shutdown/refusal recovery regressions: 2 passed in 1.18 seconds. Ruff, format and diff checks passed. The complete execution slice now has independent SPEC and quality approval. Full Task 4 remains unchecked for browser/memory/scheduler integration; proceed next to the approved C-to-B-to-C main, preserving the remaining full Agent and Task 6 requirements. No cloud, publication or remote mutation was performed.

Task 5 source inspection additionally confirms native run completion hooks occur after goal/checkpoint finalization but before extension stop observers. Persist dependency membership there only with durable native identity; resource release must still await the complete native task. Scheduler handle_run_completion normally completes the occurrence on success, so dependency waits must explicitly preserve the native active occurrence/overlap protection rather than merely launching a later notification Run.

## Task5 continuation authorization and extension boundary

The user accepted independent extensions plus necessary native hooks and explicitly requested continuation after reviewing the maintenance direction. Root stated that local Task5 native runtime/notification/Scheduler adapters may proceed under the earlier reviewable scope and corrected safeguards. The rejected defective broad batch remains unapplied; cloud and remote publishing remain deferred.

The registry offers middleware, task lifecycle, Gateway services and routers; its public contract does not directly expose pending owner handoff or goal/occurrence finalization. Preserve ECS business in its package and explicit optional native contracts. Upstream updates target only the user fork and Gitee mirror, preserving unrelated changes and migration ancestry.

## First actual native C-to-B-to-C main

After renewed user authorization, exact small core adapter patches passed automatic review and were applied. Focused interface verification passed 145 tests in 11.92 seconds and native admission 15 in 5.99 seconds. The sole actual combination run 77928 then exited successfully: 1 passed, 2 deselected in 164.38 seconds, using the existing owned PostgreSQL/Redis/two-Gateway/AIO fixture, ordinary MCP B pool and outbound program worker on one shared node/ledger with max_concurrency=1. Two native Runs preserved the original goal, one real Alpine B executed, and native present_files delivery cleared the goal; owned fixture finally cleanup ran.

This first main exposed a canonical owner ContextVar gap in central background notification checkpoint access: warning/retry occurred while the signed worker-origin notification eventually succeeded. Correct this introduced path, strengthen the current weak resource ordering assertion to observe the real queue/release sequence, and verify same-node/cumulative counters. Scheduled occurrence transfer/recovery and cancellation fences remain required. No second live run has been launched at this point; do not count this first successful main as full Task 5, complete native Agent capability or cloud acceptance.


### Task5: stable combination main, 2026-10-09

The sole stable-batch actual rerun (handle 75609) finished: 1 passed, 4 deselected / 142.71 seconds. The owned fixture cleaned its Gateway processes, PostgreSQL/Redis, Docker sandbox and owned runtime resources (pytest temporary diagnostic files remain). Strong assertions cover native C finalization/physical drain before real B start, one shared 2CPU/4GiB node with one dynamic slot, B attempt=1, exactly two native Runs, original goal snapshot/cumulative continuation count and native present_files delivery. Earlier focused batch: 242 passed, 1 deselected / 13.80 seconds, including capture-time and terminal-commit cancellation, scheduled occurrence transfer and notification-only policy. Final lint and narrow scheduled recovery identity checks precede freeze and independent SPEC then quality review. No additional live run is required for these scheduled-only/lint changes. Task5 remains unchecked until review and full requirement verification; Task4/6 remain incomplete. No cloud, remote push or fork merge performed.


Task5 independent SPEC review: FAIL (2026-10-09). Two actionable integration gaps: native MCP notification claims are global, so forwarding cannot require the claimant node to own a C source; ordinary central-source and another-node-source notifications must not become permanent dead letters. Also a fixed 100-row mixed wait scan cannot provide an exhaustive scheduled-wait validity set; unexamined receipts must not be treated as invalid during whole-occurrence recovery. Same coder is fixing both with minimal offline regressions; same SPEC reviewer will re-review before fresh quality review. Root independently ran the existing native scheduled wait/cancellation and SQL occurrence-transfer tests: 2 passed / 2.12 seconds. The 142.71-second actual BC main remains valid evidence for its single-node ordinary-goal scope, not approval of these recovery/routing edges. No additional model/cloud run started.


### Task5 final review and focused closure

Same SPEC reviewer passed after canonical shared-notification, complete/checked receipt recovery and admission-before-occurrence-transfer fixes. Fresh quality review found a lost-takeover-CAS branch that could finalize a newly completed wait; the same coder reused one predicate at both initial and refreshed candidates with fresh canonical metadata/cancel fields. Same quality reviewer re-review PASS and independently ran the real SQL race: 1 passed / 1.13s. Both reviews approve only Task5 native dependency contracts, not full Task4/6.

Root frozen-code closure command: backend/.venv/bin/python -m pytest tests/test_ecs_executor_bc_main.py -m 'not live' tests/test_ecs_executor_agent_dispatch.py tests/test_mcp_task_service.py tests/test_scheduler_goal_runtime.py tests/test_durable_context_middleware.py tests/test_scheduler_completion_consistency.py -q --tb=short. Result: 282 passed, 1 live deselected / 15.36 seconds (handle 57706 terminal). All 18 changed Python files passed Ruff check and format --check; git diff --check passed. Earlier broader batch 174 passed / 1 existing short-timing failure is retained; its targeted rerun and this final broader closure passed. No extra model run or full 27k gate was repeated during these fixes.

Cancellation semantics: native goal clear stops the overall goal and invalidates the receipt; native MCP cancel stops one B subtask, permitting its terminal cancellation result to be delivered and the still-active goal to decide next work. Existing scheduled continuation is acknowledged only after durable occurrence association; expired pending admissions use native lease CAS and deferred instance-safe cleanup.

Task5 plan and OpenSpec item checked. Full configured C browser/memory/Scheduler, fork migration/integration, operation scripts, full final backend/blocking gates and later cloud acceptance remain required. Goal/objective is not marked complete. No remote push/cloud operation.

## Task4 configured native Scheduler slice, 2026-10-09

Frozen optional host contract: NativeWorkerHost.scheduler_dispatch_enabled=False selects native ScheduledTaskService foreground-only operation; dispatch_enabled defaults True. Worker retains real native schedule/stop capabilities and completion hooks while control performs recovery, claims and automatic launches. Manual trial/trigger queues the same native occurrence. is_running preserves daemon semantics and is_available expresses foreground readiness; no request authority selects role. UI ingress remains control.

Sole live session 98786: 1 passed / 72.92s. Authenticated once schedule actually launched by native poller, remote C -> ordinary MCP Alpine B -> same-goal C. Assertions cover one occurrence/count, two Runs, goal/budget, physical drain-before-B, one shared 2CPU/4GiB node, B attempt1, native present_files and goal cleanup. Owned runtime and UUID Docker inventory cleaned; sanitized diagnostic directories retained. No recurring/live-self-stop matrix was added.

Frozen native/API/startup/boundary regression: 528 passed, 2 live deselected, 1 existing Starlette/httpx deprecation warning / 17.52s. Exact command in docs/ecs-native-testing.md; /tmp/ecs-native-scheduler-offline.txt stores output only. Root independent actual backend/.venv Scheduler file: 5 passed / 1.95s. Initial command omitted extension PYTHONPATH (4 passed/1 import failure), corrected documented path passed. All 12 changed Python files Ruff lint/format and diff check PASS.

Independent SPEC reviewer PASS by read-only code review, no extra model run. Fresh quality review PASS after read-only review of role selection, start/stop readiness, manual queuing, API/tool gates and native completion. Full Task4 browser/memory and Task6 remain pending; no cloud, fetch/push or integration performed.

## Task4 native memory slice, 2026-10-09

Configuration and acceptance only, no native runtime/storage/protocol changes. Native DeerMem canonical owner-scoped facts/summary use shared DEER_FLOW_HOME, local per-role FTS indexes; tool mode uses native memory_search/get/add. Existing shell/BC/scheduled fixture defaults remain unchanged.

Original sole main handle87116 PASS1/43.66s proved hidden UUID receipt, real native tools, central/worker revision visibility, another registered owner exclusion, original remote Run/worker owner/events, shared per-user Markdown facts and separate local FTS/no NAS SQLiteWAL. SPEC initially required actual loader expansion/base preservation, concrete safe memory-only config merge, and successful delivery rather than call-name/disk evidence. Same coder closed all three. Native AppConfig._from_yaml_text proves env expansion and preserved model/db/auth/Redis; exclusive-create merge tested for preservation and overwrite refusal.

Necessary same-case rerun handle64045 PASS1/46.71s exercised exact present_files filepaths, correlated success ToolMessage, native state artifacts and native central artifact HTTP200/body. Owned Docker inventory empty; no other B/BC/scheduled live reruns. Earlier 61memory/harness passed4.59s and 27identity passed1.24s; final loader2passed0.95s, root independent2passed1.02s. Ruff/format/diff PASS. Same SPEC reviewer frozen recheck PASS, fresh quality PASS after checking opt-in defaults, config singleton isolation, merge safety, owner/peer/index receipts and teardown. Browser/full Task4/Task6/cloud remain pending.

## 2026-10-09 native browser accepted local contract

Code SPEC and quality re-review PASS. Final zero-model control selector PASS1/19.50s (handle71782), no Run/job/model invocation, same native state/frame/input, owner/Origin/capacity denial, no replay, canonical-delete retirement and fresh other-owner browser. Owned processes cleanly exited and Docker residue0. Root independent six lifecycle tests PASS1.68s; two physical-retirement races PASS1.34s;15 changed Python lint/format PASS.

Evidence is segmented: model selector attempts38276/20021/82911/52190 did not finish GREEN; actual native model browser tools/file/finaldelivery and control input steps were demonstrated before later fixture failures. No additional model run followed. Zero-model97747 exposed stale-scope global cancellation causing fresh-owner timeout; final71782 proves repair. Reviews additionally repaired bounded identities, deferred finalizer ownership, controlled unknown results and retired Live session relaunch/initialization races. No cloud/remote/cgroup/productionWSS proof.

Initial pytest showlocals emitted inherited non-model persistent service credentials; user was informed and rotation recommended. Actual DeepSeek credential occurrences0. Owned diagnostics were scanned and redacted without printing values; emitted managed stdout cannot be withdrawn. Live-session locals disabled and browser child env restricted. No source private file or credential was changed.
