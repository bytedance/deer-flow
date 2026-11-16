# Task continuity (`deerflow/agents/task_continuity/`)

Task notes and history search, which carry a task across context compaction. The
contract, the trust boundaries and the excerpt boundary rules are in
[task continuity](../../../../../../docs/task-continuity.md).

```bash
cd backend && python -m pytest tests -q -k "task_note or task_continuity"
```

Test note capacity through the real graph, and excerpts through the real search
and read tools.

## Note capacity

- **Parallel note calls are coordinated by reservation.** A lock on one snapshot
  cannot coordinate parallel Commands.
- **Reservation and execution resolve arguments the same way.** With handle
  resolution enabled, both read the call-local argument view. That view lives in
  the current tool runtime state, outside messages and checkpoints.
- **A malformed sibling call must not break the receipts of valid siblings.**
  Skip a structurally invalid call during reservation, without a source lookup.
  Source availability and policy denial are runtime outcomes, and the slots they
  leave unused are recalculated in the next batch.

## History search

- **The role filter belongs to `history_search` only.** `history_read` takes no
  role parameter.
- **Filter archived payloads before the ranked iteration**, and preserve
  ranking, source IDs, checkpoint reachability and user and thread isolation.
- **Excerpt offsets are zero-based, half-open character offsets in the readable
  source**, so `source_text[start:end] == excerpt`. Map case-folded matches back
  to original characters, not bytes.
- **Active text wins over an archive with the same ID.** For duplicate archives,
  the first stored version supplies the text and the truncation flag, the same as
  a read by ID, so offsets refer to that text.
- **When normalization prevents an exact location**, return the opening of the
  source and mark the excerpt as not matched.
