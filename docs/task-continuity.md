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

- `task_note`: save, replace or delete a named note, with at most eight notes,
  750 characters and four source IDs per note. Parallel additions reserve the
  remaining slots for distinct new keys in model tool-call order; repeated keys
  share a slot. Non-dict sibling arguments are ignored during reservation, so
  malformed calls neither consume slots nor break valid sibling receipts. Invalid
  keys, oversized content, excess source IDs and malformed source IDs also reserve
  no slot; these structural checks use the same resolved arguments as execution.
  When artifact-handle resolution is enabled, reservations use
  resolved keys, so handles and concrete keys referring to one note share a slot.
  Excess additions return `note_capacity` without evicting existing notes or
  reporting `saved` for a write discarded because of capacity. Existing keys can
  be replaced at capacity; empty content deletes a note. Valid writes to the same
  key, including explicit deletions, retain call-order, last-write-wins merging.
  Reservations use the pre-batch notebook snapshot. Slots freed by sibling
  deletions or left unused by unavailable-source or policy-denied calls are recalculated in
  the next batch. On a capacity error, replace an existing key or retry after the
  current batch completes. This avoids predicting sibling success or serializing
  other tools. Source IDs establish readability, not semantic support; all notes
  remain model reports.
- `history_search`: keyword search over the current messages and compacted source
  batches reachable from the current checkpoint. English words and Chinese
  character bigrams are supported. Returns up to eight excerpts of at most 600 characters.
  The optional `role="user"`, `"assistant"`, or `"tool"` filters by message author
  type; omission or `null` preserves search across all roles. These values map to
  internal `human`, `ai`, and `tool` roles; returned role values stay unchanged.
  Both active and archived history are filtered before the eight-result limit.
  For example, `history_search(query="replicas", role="user")` narrows the search
  to user messages about replica counts; use `history_read` to verify the source.
  Filtering does not change ranking or guarantee retrieval of the latest message.
  A matching role does not establish truth or grant current authorization.
- `history_read`: read the exact source ID in 4,000-character pages. Results mark
  truncation and provide `next_offset` while more stored text remains.

### Matching excerpts and character offsets

Each search result includes `excerpt`, `excerpt_start`, `excerpt_end`, and
`excerpt_match`. Offsets are zero-based, half-open Unicode character positions in
the original source readable through `history_read`, satisfying
`source_text[excerpt_start:excerpt_end] == excerpt`. No ellipsis or separate
opening summary is added. Python character counting includes individual combining
characters; it does not count UTF-8 bytes, UTF-16 code units, or grapheme clusters.

For example, if `Needle` appears after 5000 characters with enough surrounding
context, searching for `needle` returns `excerpt_start=4703` and
`excerpt_end=5303`. Call `history_read(source_id=result.id, offset=4703)` to read
from that excerpt onward. The excerpt is centered on the earliest locatable term
where possible and shifts at source boundaries, up to 600 characters. Multiple
terms retain OR matching: choose the earliest source position, preferring the
shorter term when starts tie. The excerpt need not cover all terms, and result
ranking is unchanged. Repeated terms do not increase the result count.

Queries still tokenize only the first 500 characters and use the first 32 terms.
Active sources retain casefolded substring matching; archived sources retain FTS
token matching. Location shares the English-word and Chinese-bigram tokenizer.
Length-changing casefolds such as `Straße` map back to original positions; the
combining dot produced by folding `İ` follows the existing tokenization rules.
FTS normalization may not map exactly to indexed terms, such as `cafe` matching
`café`. If a complete match cannot be located, or the matched term's original span
cannot fit within 600 characters, return the source opening with
`excerpt_match=false` rather than claiming the excerpt contains the keyword.

Offsets apply only to the source readable in the same state. The active version
of an ID takes precedence over its archive. If a source was archived repeatedly
with different caps, choose the first stored version, as `history_read` does.
Fall back explicitly if the shorter version lacks the query term. `truncated`
still describes source truncation, not excerpt clipping; `next_offset` is computed
against that source. Search again after compaction, retention expiry, or state
changes; old offsets are not snapshots independent of the source lifecycle.

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
Text includes plain string content and mixed lists of strings and `type: text`
blocks, in their original order. Other typed blocks remain excluded even if they
carry a `text` field. The same extraction is used for active-history search.
Valid user answers from clarification cards are included even when their
`HumanMessage` is hidden from the UI; hidden framework injections remain excluded.

The archive lives at
`{DEER_FLOW_HOME}/users/{user_id}/threads/{thread_id}/task-history/history.sqlite`,
outside the sandbox's mounted `user-data`. Sources have the same sensitivity as
their original task messages. Existing thread deletion removes this directory;
there is no cross-thread search or separate global index. On multiple hosts,
workers need the same thread filesystem to read these local archives.

Checkpoint state holds batch references and the user/thread scope binding.
Every history reader validates this metadata, including source lookup, capture
failure recovery and durable-context rendering. Malformed history reports
`unavailable` rather than aborting the task; a successful capture replaces it
with valid metadata. Existing valid references can still be checked, subject to
the same scope and retention rules. Missing history remains uninitialized.
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
and each shortened source carries `truncated: true`.
Eviction happens before replacement insertion in one write transaction.
Competing captures serialize retention decisions; if insertion still exceeds
capacity, rollback preserves the previous batches. Duplicate capture protects
the current batch even when the configured retention limit is reduced.
Storage failure preserves
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

`backend/tests/test_task_note_capacity.py` drives real `create_agent` graphs with
a deterministic model, the production `task_note` tool and `ThreadState`. It
covers sync/async parallel capacity, receipts, full/delta checkpoints, reverse
completion order, repeated keys, deletion followed by retry, and task isolation
without calling a live model API.

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
