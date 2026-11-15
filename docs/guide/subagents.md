# Sub-Agents

Web chats accept direct model choices such as “ask MODEL to handle this”, “use MODEL for this turn”, and “from now on use MODEL”; Chinese equivalents are supported too. A child choice leaves the main model unchanged, a one-turn choice leaves defaults unchanged, and a conversation choice uses the existing browser-local thread override without changing account preferences. Choices resolve against available configurations and optional `models[].aliases`; ambiguous names or scopes show a selection card before execution, while delegation still requires enabled subagents (Ultra mode).

When a sub-agent ends with `return_direct=True` tools, including tools contributed by extension middleware, their outputs are returned in tool-call order. A failed tool marks the task as failed while preserving the batch outputs.

After its stream closes, a cancelled sub-agent keeps its execution slot until
sandbox cleanup and extension task-stop notifications finish under their existing
error and timeout policies. Repeated cancellation does not abandon this cleanup.
Task-stop reports an interrupted execution as aborted, preserving any completed,
failed or timed-out outcome already published before cancellation.

Ordinary `task` calls accept `context_mode="isolated"` (default) or
`context_mode="snapshot"`. Isolated tasks receive their delegated prompt as
before. Snapshot tasks also receive the parent's retained conversation and
compaction summary, captured at dispatch as historical background. This helps
handoffs that depend on earlier requirements or failed approaches, at the cost
of additional input tokens. Retained text, tool-call descriptions/results, and
JSON-serializable media input blocks are carried over. Binary or otherwise
unserializable media blocks become an explicit omission notice; surrounding
conversation remains available. Parent system prompts, hidden framework
messages (such as injected memory and todo reminders), reasoning blocks, tool
execution metadata, and pending tool calls are excluded. Tool-call descriptions
require a retained matching result, including calls alongside the current task.
Valid hidden user clarification responses remain part of the conversation. The child
keeps its own role, model, tools, and skill restrictions. Parent tool records
cannot satisfy child execution checks. Parent and child histories evolve
independently afterward; shared sandbox/filesystem behavior is unchanged.
Snapshot mode does not restore already-compacted messages or promise prompt
cache reuse. Durable `batch_task` items still require self-contained prompts.

Native document blocks are retained in snapshots. Their textual content, titles,
and context use the same reserved-tag and input-boundary neutralization as other
historical text; encoded media and URL sources are preserved without decoding.

For a manual, synthetic comparison of complete handoffs and snapshots, see the
[context snapshot evaluation](../../backend/scripts/benchmark/context_snapshot/README.md).

Custom Agents support an optional Unicode display name, including Chinese and
emoji. Open an agent's **Agent settings → Display name** to set it (up to 100
Unicode code points), or leave it blank to show the existing identifier. Control
characters and bidirectional formatting controls are rejected; ordinary multilingual
text and emoji are supported. Invisible-only names and invisible formatting
characters such as zero-width spaces are rejected. Invalid display names in
older or hand-edited storage fall back to the agent identifier when read;
a warning identifies the affected agent.
Re-bootstrapping preserves valid display names. The gallery,
chat header, and welcome page use this label; URLs and API calls continue to use
the stable English `name`. API callers can pass `display_name` to agent creation
or update requests; an omitted update preserves it and `null` clears it. The
same optional field is supported in the agent's `config.yaml`.

The new-Agent page confirms creation only after the latest `setup_agent` call
succeeds and the persisted Agent can be read back. A tool failure or an
unconfirmed write keeps the draft visible and restores **Save agent** so the
operation can be retried instead of reporting a false success. Read-back results
from a superseded Save attempt cannot change a newer attempt or its feedback.

Saving an unrelated Agent setting preserves its existing thinking and reasoning
defaults, including while the model catalog is loading, unavailable, or missing
the configured model. Explicit reasoning edits are saved independently; choosing
a different known model clears defaults that the new model cannot support.
Saving a model switch waits until the selected model is available; unrelated
edits remain saveable without the catalog. Incompatible saved reasoning values
are shown explicitly so they can be replaced with Inherit or a supported value.

Custom Agents migrated to `agent_storage.backend: db` remain editable through
Agent settings and `update_agent` while the importer retains their old files
for rollback. See [Agent Storage](../../backend/docs/CONFIGURATION.md#agent-storage)
for the migration procedure.

Custom Agents can also be moved between DeerFlow users or deployments from the
Agents gallery. **Export Agent** downloads a versioned
`*.deerflow-agent.json` package containing the portable definition and
`SOUL.md`; **Import Agent** validates that package and lets the receiving user
choose a local name. Invalid packages show validation messages so you can correct
the package and retry. Imports never overwrite an existing agent. Packages carry
model, tool/MCP, skill, knowledge, sub-agent, reasoning, and memory-policy
settings, but deliberately exclude memory contents, conversations, credentials,
and operator-owned GitHub bindings.

Sub-agents are an optimization, not the default response to a complex request.

After Stop interrupts a delegated task before it returns a reply, the next user
turn marks that earlier task as cancelled in the agent's durable context so it
can retry. Existing replies are preserved. Older replies without status metadata
may still appear in progress; their outcome is not inferred from their text.
The durable delegation ledger distinguishes calls by run, provider tool-call
ID and the response that issued them, so a later user turn, or a later response
in the same run, can reuse an ID without replacing earlier work or escaping the
per-run delegation cap. A `task` call that needs approval keeps its ledger entry
across the pause: the approved call records its result there, and a rejected or
denied call is recorded as cancelled.

The lead agent can spawn sub-agents on the fly — each with its own scoped context, tools, and termination conditions — when delegation has clear net benefit from real parallel latency, specialist capability, or context isolation. It keeps interdependent scopes and overlapping side effects out of parallel dispatch; a bounded sequential chain can still run in one sub-agent when specialist or context-isolation benefit clearly wins. The lead uses the fewest useful sub-agents and re-evaluates later batches instead of fanning out solely because a task is large or multi-step. Sub-agents report back structured results, and the lead agent verifies and synthesizes them into a coherent output. Deterministic tool receipts cover both direct tool messages and state-updating `Command` results such as delegated `task` responses; when the receipt ledger reaches its context budget, it retains the newest actions and their original receipt IDs. Operators can disable this provenance layer with `verification.receipts_enabled: false`. Their configured skills are resolved from the same user-scoped catalog as the lead agent, so user-owned custom skills remain available without exposing another user's version. Their internal AI and tool messages stay scoped to the delegated graph instead of entering the parent chat stream. Reloaded thread history enforces the same boundary: callback-captured sub-agent AI responses remain available in run-event diagnostics but are excluded from the parent transcript, while the parent `task` result remains attached to its subtask card. Long-running sub-agents compact older history when summarization is enabled and re-inject the summary as guarded, hidden durable context before continuing, so recent assistant/tool activity remains grounded in the task. Their system instructions, including the role and report contract, survive compaction; if only those instructions and the current request would be summarized, compaction is skipped. Provider/model request failures are reported as failed sub-agent tasks rather than successful results, so the lead agent and Web UI can react to them correctly. Concurrent parent runs also receive independent server-side sub-agent execution IDs, so a provider that reuses a tool-call ID cannot make one run poll, cancel, or clean up another run's background task. Collapsed sub-agent cards show the effective model and, when the provider returns usage metadata, a cumulative token total that updates after each completed sub-agent LLM call and persists after a reload. When token usage tracking is enabled, completed sub-agent usage is attributed back to the dispatching step from that run's terminal tool-message metadata rather than a process-global provider-ID cache.

When expanded sub-agent cards load persisted steps, delayed history responses
fill missing timeline entries without replacing complete steps already received
from the live stream with truncated previews.

Sub-agent cards keep unrecognized structured task statuses in progress. Accompanying
result text does not turn an unknown status into success or failure.

Cancelled or timed-out background sub-agent executions retain provider-reported token usage from completed model calls, including responses received before their next progress update. Final usage delivery to the parent run does not count earlier progress snapshots twice.

For `tests_passed:go test ./...`, packages marked `[no test files]` or `[no tests to run]` do not veto a passing summary from another package. Runs with only zero-test package summaries remain `UNVERIFIED`; failures still take precedence. Under `-v`, a record whose per-case lines are all `--- SKIP` also remains `UNVERIFIED`: Go exits 0 and prints the same `ok` banner, so nothing ran to pass. Non-verbose output cannot separate an all-skipped package from a passing one and stays trusted as recorded. This checks recorded execution evidence, not claim correctness.

For `tests_passed:cargo test`, a complete passing target summary can coexist with
empty unit, integration or documentation targets. Complete zero-pass successful
summaries do not veto that sibling evidence. All-empty or all-ignored runs and
bare `test result: ok` banners remain `UNVERIFIED`; incomplete zero-test summaries
are kept as vetoes, and failures still take precedence.

For `tests_passed:python -m unittest`, a complete `Ran N tests in ...s` / `OK`
summary must include at least one ordinary passing test. Skips and expected
failures do not count as passes. Successful runs with all-skipped,
all-expected-failure, empty or incomplete summaries remain `UNVERIFIED`;
nonzero exits, failures and unexpected successes still take precedence.

For `tests_passed:node --test`, complete TAP or spec counter summaries must
contain an actual pass and no failed or cancelled tests. Individual TAP `ok`
points do not prove the run passed. Empty, all-skipped, all-todo, incomplete or
inconsistent summaries remain `UNVERIFIED`; execution and shell-provenance
checks still apply. Summary detection uses the complete recorded tool output
before retaining a bounded diagnostic tail, so later TODO stacks or warnings
do not erase the test evidence. Complete, consistent Node counters take
precedence over incidental log text such as `12 passed` or `2 errors`;
independently shaped summaries from other runners still contribute evidence.
Pytest sibling summaries retain warning counts and the optional human-readable
duration suffix printed for runs lasting at least a minute, such as `(0:01:05)`.

`tests_passed` evidence pairs each command with its own result, even when a
provider reuses a tool-call id in a later response. Each run stays a separate
entry in execution order, so a later failing run is decisive and an earlier
run's output is never credited to another command.

For Maven and Gradle test acceptance, a `BUILD SUCCESS` / `BUILD SUCCESSFUL`
banner alone remains `UNVERIFIED`: builds can succeed without running tests.
Complete `Tests run: N, Failures: F, Errors: E, Skipped: S` or `N tests completed`
summaries establish a hold only when at least one test ran without a reported
failure. Zero-test or all-skipped modules do not supply positive evidence;
failures in any module take precedence over passing counts.

For file acceptance criteria, an empty regular file in the shared workspace can satisfy `file:<path> exists` and `file_written:<path>`, including on remote sandboxes. It fails `file:<path> non-empty` with a deterministic empty-file result.

To require CSV header columns, set a `task` or `batch_task` item's criterion to
`file:../outputs/report.csv csv-columns:["id","name"]`. The JSON array must contain
unique, nonempty, UTF-8-encodable column names. Names match exactly (case and
whitespace included), in any order; extra columns are allowed. Checks read only a bounded prefix and parse
the first comma-separated logical record, supporting double-quoted fields, doubled
quotes, embedded newlines, and an optional UTF-8 BOM. Data rows are not validated.
Empty files, missing required columns, malformed or invalid UTF-8 headers, and
empty or duplicate header names return `does not hold`. Headers over **50,000 bytes**, incomplete reads,
invalid criteria, unavailable workspace access, or exhausted read budgets return
`UNVERIFIED`. A large file can satisfy the check when its complete header fits the
budget. A definite syntax error within that header remains a checked negative
regardless of later data rows; truncated quoting remains `UNVERIFIED`.
Reads use the same authorized, scoped transport as JSON checks below:
50,001 bytes maximum; remote reads have a 5-second command timeout (10 seconds for
the provider call). Local reads and parsing share a cooperative 5-second deadline;
remote parsing has its own 5-second deadline starting after the read returns.
These checks do not interrupt an in-progress filesystem or parser call. Concurrent
writes are not an atomic snapshot. This does not validate data types, row counts,
or business meaning.

To request JSON syntax validation, explicitly set a `task` or `batch_task` item's
`acceptance_criteria` to `["file:../outputs/report.json json-valid"]`. Checks cover only
complete UTF-8 JSON files within the shared workspace, up to **50,000 bytes**.
Valid syntax returns `holds`; empty files, syntax errors, non-UTF-8 content, or
`NaN`/`Infinity` return `does not hold`. Oversize files, incomplete reads, out-of-scope
paths, or parser resource limits return `UNVERIFIED`.
Reads are capped at 50,001 bytes to detect oversize content. Remote results are checked
for a completion marker, the read exit code, and the probed size. Remote providers lacking
the required probe tools leave the result unverified rather than falling back to full-content
reads. Concurrent writes of the same size do not yield an atomic snapshot.
Local checks authorize sandbox access before resolving paths or probing metadata, and recheck
before reading content; revoked permissions return `UNVERIFIED` without revealing existence.
Remote probes report missing files only with a searchable ancestor and in-scope canonical path;
inaccessible directories remain `UNVERIFIED`. UTF-8 BOMs are rejected. Top-level scalars,
duplicate keys, and syntactically valid large numbers can pass, without validating schemas,
fields, or business semantics. Other file criteria are unchanged, and `.json` files are not
checked automatically. This criterion standardizes verdicts, path boundaries, and read limits
instead of requiring ad hoc bash/Python checks, and makes insufficient evidence explicit.
Execution completion status and automatic retry policy are unchanged.

Content-less sub-agent final messages report `No response generated` instead of the literal text `None`. A content-less provider-error fallback reports its structured error detail when available.

An ordinary `task` also receives a defensive snapshot of the dispatching run's current uploads. This lets eligible sub-agents use `list_uploaded_files` to find earlier-turn files without returning same-turn attachments as historical. Delayed or recovered `batch_task` workers leave this tool disabled because they have no valid turn-local upload boundary.

Embedded Python uploads use the same captured content for the saved document and its Markdown conversion, even if the caller's source changes during upload. Converted Markdown receives a free filename with a numeric suffix on collision, preserving user-authored Markdown and companions from earlier uploads. The upload response reports the actual companion filename.

历史上传发现支持稳定续页：`list_uploaded_files` 默认每页 20 项、最多 100 项，
将返回的 `next_cursor` 作为下一次调用的 `cursor`，保留相同过滤条件，直到末页不再
返回游标。目录元数据或调用上下文变化时会明确要求重新枚举；详情见
[文件上传文档](../../backend/docs/FILE_UPLOAD.md)。

Native subagent hard timeouts publish `TIMED_OUT` at the execution deadline while cleanup continues under supervision. Durable batch workers wait up to 60 seconds for cleanup before recording the published outcome and applying the configured retry policy. Unfinished executions retain capacity and sandbox leases until teardown finishes; keep work idempotent because retries may overlap late cleanup.

Durable `batch_task` workers use one app-owned plugin snapshot for tool assembly and execution. Recovered tasks adopt the new worker's plugin snapshot after a Gateway restart; plugin objects are never stored in durable task records.

Batch items can declare `depends_on` using other keys in the same batch. Ready
items run without waiting for unrelated work; waiting items consume no execution
slot. For a user-requested summary or delivery after background work, the optional
`continuation` argument registers one lead-Agent follow-up. The existing Goal
keeps ownership when active. See [batch dependencies and follow-up](../../backend/docs/BATCH_CONTINUATION.md)
for authorization, cancellation, recovery and result semantics.

When a source run fails or hits a hard stop, the Gateway attempts each batch
cancellation independently. A failed cancellation logs the batch and run IDs.

Ordinary `task` delegation and explicit durable `batch_task` execution share the startup-scoped `subagent_runtime` process capacity. Batch mode keeps large independent item sets in SQL with separate total, live, and running limits, restart recovery, bounded results, and a thread-scoped Web UI panel. The panel pages through bounded previews on demand and opens a selected item’s stored report and captured evidence for review. Citations open the matching saved excerpt without contacting the provider, and an open result refreshes until the item finishes and when the item list observes a later retry. Closed result dialogs do not fetch full details. Bulk stored results remain available through the owner-scoped JSONL export, while internal execution and authorization context never enters owner-facing responses. If the batch worker is later stopped or disabled, threads with persisted batches retain read-only item inspection and JSONL export; execution controls remain disabled until the worker is running again. See `config.example.yaml` and [the implementation contract](../../docs/plans/2026-08-24-subagent-batch-capacity-implementation.md) for limits and recovery semantics.

Queued requests finish removing their queue entry and returning any transferred
slot before cancellation propagates. The cleanup waits for the capacity lock
without its own deadline. Cancellation during timeout cleanup takes precedence
over the queue timeout.

While durable batch tools are available, a later owner turn can explicitly inspect selected results with `read_batch_result(batch_id, position=0, offset=0, max_chars=4000)`. The reader is restricted to the current user and thread, including in explicitly bound SDK graphs. It returns one window of a JSON document containing the stored report, execution/error state and separate acceptance criteria/verdict, without starting or waiting for work. Concatenate `content` windows before parsing: pass `next_offset` and the returned `revision` as `expected_revision` until `next_offset` is null. A changed item returns `restart_required`; discard prior windows and start at zero. Use `next_position` for a selected next item within `batch_status.total_items`. The maximum window is 8,192 characters; metadata shares the window budget, and JSON response framing adds overhead. `result_truncated` means storage already capped the report; continuation cannot recover discarded content. A succeeded item is not an accepted task, and unchecked criteria remain UNVERIFIED. No automatic result ingestion, waiting loop or UI change is added.

The complete escaped response also fits within 10,000 characters and the bound host's positive `tool_output` externalization/fallback limits, so normal budgeting preserves continuation JSON. Smaller limits can shorten a window; `budget_too_small` means the operator must raise the budget instead of retrying a zero-length page. Limits too small even for that error envelope cannot provide a usable structured response. Explicit SDK graphs with a custom output-budget middleware should supply the same `AppConfig` through `SubagentRuntime`; default graphs use default reader limits.

Offline acceptance: `cd backend && PYTHONPATH=. uv run --locked pytest tests/test_batch_result_reader.py -k 'real_submission_worker or sdk_factory_graph' -q`. This exercises real submission, deterministic worker completion, database reopen and registered graph consumption; external model execution is replaced by a fake model/executor.

Durable knowledge-research results also export nullable `result_artifact.knowledge_sources` snapshots. Each retained source pairs a citation ID in the stored report with the exact excerpt captured by `knowledge_search` or a delegated `task`, plus its RAGFlow dataset/document/chunk locator and pages. The existing authenticated `GET /api/threads/{thread_id}/subagent-batches/{batch_id}/results.jsonl` remains the entry point: find a report's `#knowledge-<id>` link in that row's `sources` by `id` to inspect the evidence after a Gateway restart or provider change. Compact item queries do not include these snapshots; clickable citations are available in the selected result dialog, not batch previews.

Browser review keeps at most 100 sources, with 16,000 characters per excerpt and bounded identifiers/names. Sources excluded by these read limits increase the displayed omission count; the persisted snapshot and JSONL export retain their original contents.

Snapshots preserve whole excerpts, not freshly fetched provider content. They inherit the 100-source/1,000,000-text-character forwarding limits; the serialized snapshot has a separate character budget equal to `subagent_batches.max_result_chars`, in addition to the report's existing budget. `knowledge_sources.omitted_count` reports referenced records omitted by forwarding, snapshot projection checks or snapshot budgeting; malformed or unsupported producer artifacts filtered before candidate selection are not counted. Report truncation limits selection to complete citations in the stored text. Old/plain results have no snapshot (`null`); no historical evidence is reconstructed. Gateway startup adds a nullable JSON column through migration `0033_batch_result_artifact`. Back up the database before migrating; downgrading drops evidence snapshots while preserving report text. Cancelled, failed and stale attempts do not publish evidence, and explicit retries clear previous snapshots.

Explicitly enabled nested `task` delegation propagates omitted opaque source IDs in its captured artifact. Each outer report filters and deduplicates those IDs, and independently captured evidence can restore an omitted source. The durable snapshot publishes only the final count. Legacy task artifacts without omission IDs cannot reconstruct earlier forwarding losses; unknown prose citations are not treated as captured evidence.

If an item's final lease expires after exhausting the retry budget, the batch reaches a terminal state once all items are terminal: `failed` when none succeeded, or `completed` when at least one succeeded. The item remains `failed` in both cases so partial results stay visible.

Paused batches also reconcile expired attempts after a worker exits. Retryable items remain queued without starting new work until you explicitly resume the batch; exhausted attempts become failed and can be retried individually.

Direct `create_deerflow_agent(...)` integrations can own the same boundary explicitly instead of relying on Gateway startup. Construct one `SubagentRuntime` and share it across every graph in that application; its `max_running`, ordinary per-run total, bound `task` tool, and optional durable-batch tools then use the same caller-owned snapshot and execution controller. A runtime with a batch repository owns a worker and must be started before graph construction and stopped during application shutdown:

```python
from deerflow.agents import RuntimeFeatures, create_deerflow_agent
from deerflow.subagents import SubagentRuntime

runtime = SubagentRuntime.from_app_config(app_config, batch_repository=batch_repository)
async with runtime:
    graph = create_deerflow_agent(
        model,
        features=RuntimeFeatures(subagent=True),
        subagent_runtime=runtime,
    )
    # Serve or invoke graph while the durable worker is running.
```

`SubagentRuntime.stop()` waits for its owned batch service to finish before propagating caller cancellation, including repeated cancellation. This drain has no timeout; repository operations and child cleanup must terminate. If service shutdown also fails or is cancelled, the first caller cancellation is preserved with the service failure as its cause.

Gateway run finalization also retains ownership through caller cancellation: it finishes terminal persistence, stream completion, and resource cleanup before propagating the interruption. Backend I/O must terminate or enforce its own timeout. Gateway shutdown includes workers still finalizing after their terminal status commits; an expired shutdown drain budget is logged and does not cancel their outstanding writes.

Cancelled, replaced, failed or hard-stopped executions stop their owned bash processes before releasing the sandbox lease on AIO and POSIX LocalSandbox, including ordinary `nohup` children. Background services from successful earlier turns remain running. Cleanup tracks inherited execution markers and process groups; it is not a security boundary against scripts deliberately escaping that ownership. Windows LocalSandbox and third-party providers retain their existing behavior.

Terminal cleanup releases the run journal and its message-sequence callback even when diagnostic logs retain a checkpoint-inspection traceback.

The factory still does not load YAML or create SQL infrastructure: the caller supplies the config snapshot, repository, and lifecycle. Because it accepts a caller-owned `system_prompt`, direct integrations also own any model-visible wording about those limits; the default middleware enforces the runtime limits regardless. The factory does not mount the Gateway owner-scoped HTTP routes or Web UI, so direct applications must expose their own result API/UI if they need those surfaces. For ordinary delegation only, `SubagentRuntime(...)` needs no asynchronous startup.

Administrators can add, edit, disable, and delete reusable worker definitions from **Settings → Subagents**. Built-in and `config.yaml` definitions remain visible there as read-only entries. The default Lead Agent can use every enabled runtime sub-agent; each page-created Custom Agent can instead allow all, none, or a selected set. That selection is enforced both in the model-visible directory and by the server-side `task` tool. Managed definitions are deployment-wide in this version and follow `agent_storage.backend`: atomic files for a local deployment or the shared application database for multiple instances.

When Gateway workers share file storage, concurrent managed-subagent creates for the same name preserve the winning definition and return one HTTP 201 and one HTTP 409. File-backed managed-subagent creation requires a filesystem supporting hard links; see [Agent Storage](../../backend/docs/CONFIGURATION.md#agent-storage).

Native workers support per-subagent `thinking_enabled` and `reasoning_effort` through YAML configuration and the managed-subagent API. Unconfigured workers keep the existing thinking-off request; the selected model's required-thinking policy, supported effort values and aliases still apply. These settings do not inherit the lead agent's thinking preferences.

For example, independent read-only research can run concurrently when the wall-clock savings outweigh duplicated discovery and synthesis cost, while a repository refactor with shared files and sequential test feedback remains with the lead agent. When `max_concurrent_subagents` is `1`, parallel and multi-batch routing guidance is disabled; delegation remains available only for material specialist or context-isolation benefit.

## Tool restrictions

Subagent `tools` allowlists and `disallowed_tools` denylists apply to middleware-declared tools as well as inherited tools, even when global authorization is disabled. Denylists take precedence; an empty allowlist excludes all middleware declarations.

Framework-generated discovery helpers (`tool_search` and `describe_skill`) are
an exception to these name-level allowlists and denylists. Adding either name to
`disallowed_tools` does not remove the generated helper. Each helper's catalog
remains limited to admitted tools or skills.

Before creating the agent graph, a final check verifies the explicit tool list
and middleware declarations against the subagent's name policy. A tool added
after the earlier filtering passes stops the build if it violates that policy.
The error identifies whether the tool is listed in `disallowed_tools` or missing
from the `tools` allowlist, so the corresponding configuration can be corrected.
Discovery exemptions apply only to the actual framework-generated helper
instances; an ordinary tool with the same name still follows the name policy.

Middleware tool declarations follow LangChain's `Sequence` contract, including lists and tuples. Restricted subagents reject non-sequence containers such as sets and generators before consuming them; the default `disallowed_tools=["task"]` also counts as a restriction. Global authorization retains its existing list/tuple declaration requirement. Extensions remain trusted operator code; tool configuration is not an isolation boundary for extension code.
