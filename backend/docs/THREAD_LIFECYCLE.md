# Gateway thread lifecycle invariants

Read this guide before changing thread branching, regeneration, edit replay, or
archive/search metadata behavior. It supplements the Gateway module guide.

**Branch/regenerate checkpoint invariant**: `app/gateway/checkpoint_lineage.py`
walks `parent_config` rather than globally ordered checkpoint history so replay
anchors stay on the selected lineage after regenerations create sibling branches.
New conversation branches persist the pre-user replay anchor before their visible
head through the state mutation graph, which preserves materialized state in both
full and delta checkpoint modes. Chronological compatibility lookup is available
only when the checkpoint head has no recorded parent link. An explicit lineage
that ends before a replay base or contains a cycle or invalid link fails closed.
Existing single-checkpoint branches are never repaired by copying a raw
checkpoint because delta state is not self-contained in one tuple.
Both lookups additionally require the replay base to be a **settled** checkpoint
(`has_pending_tasks` — no scheduled `next` tasks). A checkpoint with pending tasks
is a mid-run snapshot: resuming from it replays the writes of the node that was
about to run. Message ids alone cannot exclude those, because middleware may
rewrite a message's id inside the run that produced it — `DynamicContextMiddleware`
moves the first user turn to `{id}__user` and gives `{id}` to the injected
reminder, so every checkpoint written before it holds the same prompt under an
unmatched id. Selecting one of those re-added the original prompt *after* the
edited one, and the model answered the question the edit was replacing (#4531).
`next` is not derivable on the degraded raw-checkpoint read path, which reports no
tasks; absence of evidence stays permissive there rather than failing closed.
Edit replay resolves its base through the same lineage-first path as regenerate;
it must pass `head_checkpoint` or it silently degrades to the chronological scan
that cannot tell sibling branches apart. Branch, regenerate, and edit replay
share a deadline for the linked lookup of the replay base. Changing
`max_recursion_limit` for future runs does not affect that lookup. The Gateway
logs lookup deadline expiry and returns HTTP 504. A `TimeoutError` raised by
the checkpoint store before the deadline propagates to the generic HTTP 500
handler. The chronological compatibility lookup retains its fixed checkpoint
window.
An edit replay that pauses for tool approval stays the current attempt: the edit
remains in thread state and replaces the source turn in history. Only a failed,
timed-out or cancelled attempt restores the pre-edit checkpoint; once the pause is
answered, the resume run is an ordinary run and its failure keeps the edit.

### Chat archive

`POST /api/threads/search` accepts an optional strict boolean `archived`: omitted
or null preserves the unfiltered API, true selects only JSON boolean
`metadata.deerflow_archived=true`, and false includes missing/null/non-true legacy
flags. Both SQL and Memory thread stores filter before limit/offset and retain
owner isolation. PATCH validates archive flags as booleans; pin/archive-only
boolean metadata writes use `touch=False` to preserve activity ordering. Archive
never changes runtime status, checkpoints, files, schedules, or read permissions.
