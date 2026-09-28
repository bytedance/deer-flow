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

### 命中片段与字符偏移

每个搜索结果返回 `excerpt`、`excerpt_start`、`excerpt_end` 和 `excerpt_match`。
偏移是可由 `history_read` 回读的原文 Unicode 字符位置，零基、左闭右开；
始终满足 `source_text[excerpt_start:excerpt_end] == excerpt`。不添加省略号，
也不额外返回开头摘要。Python 字符计数包括独立的组合字符，不是 UTF-8 字节、
UTF-16 编码单元或用户感知的字形数量。

例如，5000 个字符之后出现 `Needle`，且两侧上下文足够时，搜索 `needle` 会返回
`excerpt_start=4703`、`excerpt_end=5303`；调用
`history_read(source_id=结果.id, offset=4703)` 即可从该片段开始继续阅读。
片段围绕最早的可定位词尽量居中，到达首尾时向另一侧补齐，最多 600 字符。
多词沿用 OR 检索；按原文位置选最早命中，同起点选较短词，不要求覆盖所有词，
也不改变结果排名。重复词不会扩大结果数量。

查询仍仅对前 500 字符分词并取前 32 个词。active 沿用 casefold 子串匹配，
archive 沿用 FTS 词匹配；定位共享英文词及中文双字切分规则。
`Straße` 等 casefold 后长度变化的文本映射回原文位置；`İ` 折叠后产生的组合点
仍按现有分词规则处理。FTS 重音归一化等匹配未必能精确映射到索引词，
例如 `cafe` 检索到 `café`；无法定位完整命中，或展开后的词无法完整放入 600 字符时，
返回开头片段并设置 `excerpt_match=false`，不宣称片段包含关键词。

偏移仅针对同一状态下可读取的来源：同一 ID 的 active 版本优先于归档；
若同源内容以不同上限重复归档，选择与 `history_read` 相同的首个存储版本。
较短版本不含检索词时也明确回退。`truncated` 继续表示来源被截断，
而非片段截短；分页 `next_offset` 仍按该来源计算。压缩、保留期淘汰或状态变化后，
应重新搜索确认可用内容，不能把旧偏移当作不受生命周期影响的快照。

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
