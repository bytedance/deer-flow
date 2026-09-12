# Task continuity after compaction

Enable this optional feature to keep short task notes and recover details from
messages removed by successful context compaction:

```yaml
task_continuity:
  enabled: true
  max_batches: 32
  max_records_per_batch: 256
  max_record_chars: 16000
```

It is disabled by default and independent of `memory.enabled` and memory mode.
It augments the existing summary, goal, todos and delegation ledger. It neither
replaces those channels nor writes a long-term user profile. No embedding service
or additional model call is required by the feature itself.

The standard lead-agent builders (including custom-agent bootstrap) and
`DeerFlowClient` expose three tools through the existing authorization filter:

- `task_note`: save, replace or delete a named task note. Keep up to eight notes,
  each with 750 characters and four optional source IDs. A full notebook rejects
  new keys until an existing key is replaced or deleted. If parallel updates
  jointly exceed capacity, the reducer retains the last eight insertion-ordered
  keys; inspect the next injected notebook for the retained entries. Source IDs are checked
  for availability, not semantic support; all notes remain model reports.
- `history_search`: keyword search over the current messages and compacted source
  batches reachable from the current checkpoint. English words and Chinese
  character bigrams are supported. Returns up to eight 600-character excerpts.
- `history_read`: read the exact source ID in 4,000-character pages. Results mark
  truncation and provide `next_offset` while more stored text remains.

An active skill's tool policy and runtime authorization still apply. The model
may need more than one keyword search. Search is lexical; paraphrases are not
reliably matched. Notes and retrieved text are historical data, never new
instructions or proof that a reported action actually succeeded. Task notes are
injected in the existing hidden, escaped human data channel; the system channel
contains only a static authority contract.

The task-note channel normalizes every write before checkpointing, including
first writes and `Overwrite` state replacements through the Gateway or direct
integrations. Malformed entries and deletion markers are dropped, only the last
eight valid notes are kept, and every retained note is marked `model_report`.
The durable-context reader applies the same validation to existing state. Direct
state writes check source-ID syntax, not source availability or semantic support;
only `task_note` checks availability before accepting a citation.

## Storage and lifecycle

Successful automatic and manual compaction archive the visible user/assistant
text, tool-call names/arguments and tool-result text that will leave the active
message list. System messages, framework injections, reasoning fields, artifacts,
images and binary blocks are excluded. Visible attachment references stay as text;
this feature does not copy attachment bytes. A source ID includes its content and
message identity, so changing a message produces a different source version.
Valid user answers from clarification cards are included even when their
`HumanMessage` is hidden from the UI; hidden framework injections remain excluded.

The archive lives at
`{DEER_FLOW_HOME}/users/{user_id}/threads/{thread_id}/task-history/history.sqlite`,
outside the sandbox's mounted `user-data`. Sources have the same sensitivity as
their original task messages. Existing thread deletion removes this directory;
there is no cross-thread search or separate global index. On multiple hosts,
workers need the same thread filesystem to read these local archives.

Checkpoint state holds batch references and the user/thread scope binding.
Rolling back to an old checkpoint cannot reveal future batches. Copying a
checkpoint to another user or thread does not grant access to the original
archive. A fork may inherit ordinary notes/messages through existing checkpoint
copy behavior, but this feature does not copy archive files to the fork. Branch
creation clears the parent archive references and status; inherited note citations
may consequently be unavailable and need fresh verification in the branch.

Retention is bounded by the configured batch/record/text limits and a 32,768-page
SQLite ceiling (128 MiB for the default page size). The oldest physical batches
expire as new ones are captured, even if an older checkpoint still refers to
them. Read/search report `partially_expired` or `unavailable`; missing sources must
be re-verified. `omitted_records` describes the latest capture's record limit,
and each shortened source carries `truncated: true`. Storage failure preserves
ordinary compaction and marks history unavailable; it does not undo a successful
summary. Async writes are offloaded and drained before cancellation returns.
History tools preserve `unavailable` after a capture failure, even when older
sources can still be read. `scope_unavailable` denotes a scope mismatch instead.

Subagent compaction does not archive into the parent's thread. The feature does
not transfer arbitrary parent state into children and does not resume a stopped
run automatically. Direct `create_deerflow_agent` integrations can explicitly
compose these middleware/tools; automatic installation is limited to the standard
lead builders and `DeerFlowClient`.

## Evidence

[The historical experiment package](experiments/task-continuity-20260912/README.md)
contains the original A/B/C/D protocol, scripts and results. Those numbers describe
an independent replay prototype under forced compression, not this production
implementation or complete DeerFlow baseline behavior. Its vector-versus-keyword
comparison did not establish a stable net benefit, so this implementation has no
vector dependency.

`backend/tests/test_task_continuity.py` exercises source recovery after actual
graph compaction and checkpoint resume, scope/rollback isolation, retention,
truncation, failure behavior and tool contracts. The manual live integration check
uses the production middleware and native tools with synthetic history:

```sh
cd backend
uv run python scripts/manual_task_continuity_check.py \
  --endpoints /path/to/private.json --output /tmp/task-continuity-check.json
```

The private JSON contains `llm_base`, `llm_model` and optional `llm_key`; never
commit it. The check deliberately asks the summary to omit exact batch codes,
then rebuilds the graph and requires source search/read, a cited task note and an
actual correct JSON manifest. This verifies controlled recovery mechanics; it is
not a production acceptance rate, deployment check or quality benchmark.

The completed checks and exact clean-base comparison are recorded in
[implementation validation](experiments/task-continuity-20260912/VALIDATION.md).
