# RFC: structured internal context boundary (issue #3145)

**Status**: draft for discussion, no code in this PR
**Scope**: design only — read this before any UploadsMiddleware / export refactor lands
**Related**: bytedance/deer-flow#3138 (split summary), #3107 / #3131 (origin), #3145 (this issue)

## Why this is an RFC and not a patch

The other three #3138 follow-ups (#3144 docstring boundary, #3146 structured subagent_status, #3147 derive subtask state from messages) are mechanical refactors with clear contracts. They each landed in one or two days with focused PRs (#3153 / #3154 / #3158).

This one is not. It changes the contract of message content itself — what UploadsMiddleware injects into the user's HumanMessage, where it lives in LangGraph state, how the prompt the LLM sees gets assembled, how older threads keep rendering, and how user message deletion cascades. Codex's second-pass review surfaced four deep risks that any naive "extract to a structured field" patch would walk straight into. We need agreement on the shape before writing code.

## Current state (Symptom)

`UploadsMiddleware.before_agent` does this:

1. Reads `additional_kwargs.files` from the last HumanMessage to learn what the user just attached.
2. Builds an `<uploaded_files>...</uploaded_files>` text block listing both the new uploads and any historical uploads still on disk for that thread.
3. **Prepends** that block to the HumanMessage's `content`. The block now lives inside the user message that gets persisted into LangGraph state forever.

The frontend then has to scrub the block out of every consumer that shows user content (`stripUploadedFilesTag` in the UI render path, `stripInternalMarkers` in the export path). #3131 BUG-006 exists because someone forgot to scrub it in chat export.

`DynamicContextMiddleware` (memory / current_date / system reminders) uses a different pattern: it injects a separate `hide_from_ui: true` HumanMessage **before** the user's message. The frontend filters those by `additional_kwargs.hide_from_ui === true` and never has to string-strip anything from the user's actual content.

So we already have two patterns in production for "context the LLM needs but the user must not see":

| Path | Where it lives | How frontend hides it |
|---|---|---|
| `<uploaded_files>` | Inside user HumanMessage `content` | Regex strip in render + export |
| `<system-reminder>` / `<memory>` / `<current_date>` | Separate HumanMessage with `additional_kwargs.hide_from_ui = true` | `isHiddenFromUIMessage` filter |

The fragility ranking is unambiguous: pattern 2 has zero accidents in the issue history, pattern 1 owns every leak ticket we have seen so far.

## Constraint: the LLM still needs the upload context in the prompt

We cannot just stop emitting the block. The LLM relies on `<uploaded_files>` to know what files exist, where they are mounted, and how to read them. The agent's first turn would otherwise have no way to discover a file the user uploaded right before sending. So whatever we do, the model's view of the prompt must still contain that information.

## Candidate designs

### A. Adopt pattern 2 — separate `hide_from_ui` HumanMessage

UploadsMiddleware behaves like DynamicContextMiddleware. The hidden HumanMessage carries the `<uploaded_files>` block; the user's HumanMessage stays pristine.

**Pros**
- Same `isHiddenFromUIMessage` filter already covers it on the frontend — no new string-stripping code path to maintain.
- `stripInternalMarkers` becomes pure defence-in-depth (kept, but expected to be unreachable on new threads).
- Consistent with the existing DynamicContextMiddleware contract — only one in-band injection pattern is left, not two.

**Cons**
- The "where in the message list does this hidden message land relative to the user message?" question is non-trivial — see [Constraint 1] below. LangChain's prompt renderer does not promise to preserve any specific ordering when two messages share neither id nor explicit position.
- DynamicContextMiddleware handles ordering with an **ID-swap trick** (steal the original user message's id, give the user message a derived `{id}__user` id, append after). UploadsMiddleware would have to replicate that, and that contract is currently undocumented inside DynamicContextMiddleware itself.
- Multi-turn behaviour needs explicit treatment — see [Constraint 2].
- User message deletion needs explicit treatment — see [Constraint 3].

### B. Custom content-array block type

Encode the upload context as `{type: "internal_context", subtype: "uploaded_files", payload: {...}}` inside the user HumanMessage's content array (LangChain content arrays already support type-tagged blocks for images and reasoning). Frontend filters blocks by `type !== "internal_context"`.

**Pros**
- One message per turn, no ordering decisions, no deletion cascade.

**Cons**
- LangChain content arrays are a Python-side contract that several providers (Anthropic, OpenAI, vLLM) reshape on the way out to the model. There is no documented support for custom block types — a provider that doesn't recognise `"internal_context"` will either drop it or pass it through verbatim, leaking the JSON into the prompt. Same risk surface as the current string injection, just on a different layer.
- Every frontend content extractor (`extractContentFromMessage`, `extractReasoningContentFromMessage`, `extractTextFromMessage`, `parseUploadedFiles`, `stripInternalMarkers`, the markdown / export pipelines, plus anything in `core/messages/`) would need to learn the new block type. Higher migration cost than (A) and doesn't solve the ordering question more cheaply than (A) does.

### C. `additional_kwargs.internal_context` and prompt-time merge

Move the context completely out of `content` into `HumanMessage.additional_kwargs.internal_context: {...}`. Backend reassembles the prompt the LLM sees inside a new `before_model` step that splices the kwargs back in front of the content.

**Pros**
- Cleanest in-band / out-of-band split. The user's content is exactly what the user typed.
- Frontend export and render never see the context at all — no filter, no strip.

**Cons**
- What the LLM sees and what LangGraph checkpoints store are now different shapes. Replay / debug / langfuse trace inspection becomes harder: anyone reading a checkpoint has to also run the merge step in their head to reconstruct the actual prompt the model received. We have already burned hours debugging "the checkpoint says X but the model clearly saw Y" in #3107 / #3131. This widens that gap.
- The merge step is a single failure point. A bug there means the LLM stops seeing upload context. Pattern (A) fails open (the hidden message is still there) — pattern (C) fails closed.

### Recommendation

**A**, with the four constraints below treated as part of the spec, not as follow-ups. Lower implementation risk than B (no new content-block contract), higher debuggability than C (checkpoints match what the LLM sees), and structurally consistent with the only injection pattern we already trust.

## Constraints the design must address

### Constraint 1: ordering between the hidden context message and the user message

The user message is identified by the id the frontend sent on the wire. If UploadsMiddleware simply appends a hidden HumanMessage with a fresh id, LangChain's `add_messages` reducer will append it **after** the user message — too late for the LLM to consume the context before answering the user.

DynamicContextMiddleware solves this with the ID-swap trick at `_make_reminder_and_user_messages`:

```python
stable_id = original.id or str(uuid.uuid4())
reminder_msg = HumanMessage(
    content=reminder_content,
    id=stable_id,                                   # ← steals the user message's id
    additional_kwargs={"hide_from_ui": True, ...},
)
user_msg = HumanMessage(
    content=original.content,
    id=f"{stable_id}__user",                        # ← user message gets a derived id
    name=original.name,
    additional_kwargs=original.additional_kwargs,
)
```

`add_messages` keys on `id`; the reminder replaces the original entry, and the user message is appended next. The pair becomes adjacent and the ordering is stable.

**Decision required**: do we extract this trick into a shared helper in `deerflow/agents/middlewares/_message_ordering.py` and have both DynamicContextMiddleware and UploadsMiddleware call into it? Or do we let UploadsMiddleware copy the four lines and accept a soft contract? The former is cleaner; the latter is faster. I lean towards extracting — the next middleware that needs an injection (memory writeback? skill activation?) will hit the same problem and we'd rather not discover a third copy.

### Constraint 2: multi-turn upload state should not balloon the prompt

Each user turn currently re-runs `before_agent`. With pattern A, naively that appends a *new* hidden upload-context message to state every turn — even if no new file was uploaded. After three turns the LangGraph thread state carries three hidden messages each containing the same historical file list, and the model context window is consumed by duplicate content.

Two sub-options:

- **A.1** — One hidden context message per turn (the natural shape of B's reducer). Accept the duplication in state, count on prompt truncation / summarisation to absorb it. Simpler. Probably what we ship first.
- **A.2** — Replace the previous turn's hidden context message instead of appending: use a stable id like `__upload_context__` (or `__upload_context__{thread_id}`), and `add_messages` will replace in place. The LangChain reducer is keyed by id, so this is one line of work.

I lean **A.2** because it's a one-line change and it directly answers the "every turn the prompt gets bigger" concern Codex raised. But there is a subtle catch: A.2 means *the historical thread no longer remembers what files were available on previous turns* — the hidden context is "now" rather than "then". If we ever need to debug "why did the model think file X existed on turn 2?" we won't be able to look at message 2's hidden sibling, only the latest one. Decision needed.

### Constraint 3: user message deletion cascade

The current code has no deletion logic for the DynamicContextMiddleware-style hidden message either, so this constraint is partially pre-existing. But pattern A makes the gap concrete:

- User deletes message N from the thread.
- The hidden context that lives at N's position (or near it) is now orphaned.
- Next turn renders without that context block. Whether the LLM still has it depends on whether the deletion logic also removed the sibling.

Two options:

- **B.1** — Add an `additional_kwargs.upload_context_for_message_id: "<user-msg-id>"` link on the hidden message. The thread deletion handler in the gateway router that already removes thread metadata also walks state messages and drops any whose `upload_context_for_message_id` points at a now-missing user message. Same shape would work for DynamicContextMiddleware retroactively.
- **B.2** — Punt: no cascade today, document as known-issue, fix in a separate PR. This matches DynamicContextMiddleware's current behaviour (which also leaks orphan reminders) so it's not a regression. But it leaves the test surface incomplete.

I lean **B.1** done in the same PR — the link annotation is trivial, the cascade handler is ten lines, and it fixes the pre-existing DynamicContextMiddleware gap as a bonus.

### Constraint 4: migration / dual-read, not dual-write

Codex's original suggestion of "backend dual-writes both shapes for one release, frontend prefers the new one, then drop the old shape" has a fatal flaw: the LLM sees both shapes simultaneously. The model would receive the upload context twice in its prompt, once from the in-band block in the user message, once from the new hidden message. Same files listed twice — confuses tool selection and wastes tokens.

Correct shape: **dual-read on the consumer side, single-write on the producer side**.

- Backend: cut over UploadsMiddleware to write only the new shape (hidden message). Stop prepending `<uploaded_files>` to user content for any new turn.
- Frontend: keep `stripInternalMarkers` as defence-in-depth — it covers every historical thread that has the in-band block, until those messages eventually scroll out of view via summarisation or pagination.
- Tests: a regression case that loads a historical-shape thread (in-band block in user content) and asserts the export still scrubs cleanly.

This is the same pattern PR #3131 used for the structured subagent_status migration — fallback path on the consumer, single new shape on the producer, telemetry-driven retirement of the fallback. It works there, it should work here.

## Test plan (when this turns into code)

Backend:

- UploadsMiddleware test: one turn with a new upload → assert state contains (a) hidden HumanMessage with `<uploaded_files>` in content, `hide_from_ui: true`, `upload_context_for_message_id` linking to the user message, (b) user message with pristine original content.
- Multi-turn test (A.2 stable-id strategy): three turns with no new uploads → assert state contains exactly **one** hidden upload-context message at any point, with content reflecting the latest snapshot.
- Ordering test: assert the hidden message precedes the user message in `state["messages"]` for any model invocation.
- Deletion test: delete the user message → next state read shows the linked hidden message also gone.
- Shared helper test: if Constraint 1 picks the shared-helper path, exercise it from both UploadsMiddleware and DynamicContextMiddleware.

Frontend:

- Render test: a `hide_from_ui` HumanMessage carrying `<uploaded_files>` content never appears in the message list (existing `isHiddenFromUIMessage` already does this — pin it).
- Export test: same hidden message never appears in Markdown or JSON export.
- Defence-in-depth test: a historical user message with the in-band `<uploaded_files>` block still strips cleanly in the export (regression for `stripInternalMarkers` not getting accidentally removed).

End-to-end live verification (matches the standard #3146/#3147 pattern):
- Upload a file, send a message, verify backend thread state has the hidden sibling.
- Run the agent end to end, verify the LLM still picks up the file (existing `present_files` / `read_file` test fixture should pass unchanged).
- Export the thread, verify the path / filename never appears as a string outside the assistant's visible reply.

## Open questions for review

1. Constraint 1: shared helper (extract `_make_reminder_and_user_messages`) or per-middleware copy?
2. Constraint 2: A.1 (append every turn) or A.2 (replace by stable id)?
3. Constraint 3: B.1 (cascade in this PR) or B.2 (cascade later)?
4. Does `stripInternalMarkers` retire after a release cycle once telemetry confirms it never fires, or do we keep it as a permanent defence?
5. Are there middleware ordering concerns? UploadsMiddleware runs before LLMErrorHandlingMiddleware / SummarizationMiddleware today. If A.2's stable-id strategy collides with summarisation's compaction (which rewrites the message list), we need to either teach summarisation to preserve the hidden context message, or change the stable id strategy.

## Out of scope

- Replacing in-band `<system-reminder>` injections with anything else. DynamicContextMiddleware already does the right thing.
- The matching change to the `present_files` mechanism. That tool emits a separate AI message with `additional_kwargs.files`; the user-facing render of that message is a different problem.
- Cross-thread upload sharing (uploads attached to one thread visible from another). Not on the roadmap.

## Decision log

This section will be filled in by the PR review thread. Pinning explicit decisions here so the implementation PR can cite them.

- [ ] Constraint 1: …
- [ ] Constraint 2: …
- [ ] Constraint 3: …
- [ ] Constraint 4 retirement plan: …
- [ ] Constraint 5 middleware ordering: …
