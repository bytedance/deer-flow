# Upload context and user messages

Upload descriptions must reach the model without becoming part of the user's
stored prose. New upload turns store the validated description on the owning
`HumanMessage`:

```json
{
  "content": "Explain <current_uploads>my example</current_uploads>",
  "additional_kwargs": {
    "files": [{"filename": "report.pdf", "size": 24}],
    "deerflow_upload_context": {
      "version": 1,
      "text": "<current_uploads>…validated file descriptions…</current_uploads>"
    }
  }
}
```

`files` remains the attachment-display and upload-admission input. The Gateway
removes caller-supplied `deerflow_upload_context`; only `UploadsMiddleware`
captures it after validating the references against the runtime owner's uploads.
Existing file-count limits, outline bounds and filename/outline sanitization
continue to apply. This changes neither upload authorization nor file storage.

## Model and persistence boundaries

`InputSanitizationMiddleware` sanitizes and frames the user's original content
first, then projects the context ahead of it on a request-only copy. Native media
blocks retain their values and order. Projection preserves message IDs and does
not append a hidden sibling message, so normal replacement, deletion, checkpoint
replay and compaction manage the context together with its owning turn.

The copied envelope carries `projected: true` to prevent repeated upload prefixes
and `sanitized: true` only after the guardrail completes successfully. Both are
transient: UI/run-journal restoration removes them and restores the user text.
Never copy a projected request back into graph state. Model-facing copies and
persisted messages must not share mutable content blocks.
If original-user provenance is missing or malformed, restoration still clears
the transient markers and removes the exact owned upload prefix when present; it
does not guess how to recover user text from transport framing. A guardrail
exception retains the existing fail-open behavior and still projects the
independently captured file descriptions. A nested retry skips sanitization only
when both markers are true; projection alone cannot claim guardrail success.

Summary triggers, token/fraction retention and the context-usage estimate count
the projected context; partitioning still retains the original stored messages.
Rolling summary source preparation projects it before applying source budgets.
Parent conversation snapshots include it as inert historical data, not child
system instructions. Memory admission removes
the context metadata; file outlines are not durable user memory.

## Display and compatibility

For a supported version-1 envelope with a string `text`, the human content is
already user data. The wire version is the JSON number `1` (including `1.0`),
never a boolean or string. Chat rendering, editing/copying, conversation outlines and
Markdown/JSON exports do not remove tag-like text from it. Internal context is
never included in the export's selected fields. Attachment chips still use
`additional_kwargs.files`.

Unversioned historical messages keep the existing inline-tag cleanup and legacy
file-chip fallback. Unsupported or malformed metadata does not opt a message out
of that containment; backend projection ignores it with a debug log so repeated
history reads do not flood warnings. Assistant and hidden framework-message
filtering retain their existing rules.

There is no bulk migration of old checkpoints. Recapturing an old upload turn
can restore its explicit `original_user_content` provenance before recording a
new envelope; it never guesses which part of the user's text is internal. Without
valid original provenance, legacy-shaped file descriptions (upload tags containing
upload paths or the historical file-list preamble) stay on the unversioned inline
path. Recapture adds the current validated descriptions without declaring that
old body pristine or manufacturing original-user provenance. An unchanged current
prefix is not added twice. Bare literal tag examples remain eligible for v1;
explicit original provenance preserves even file-description-shaped user examples.
Other internal-context producers remain outside this upload-specific change.

## Verification

`backend/tests/test_structured_upload_context.py` exercises capture, sanitization,
checkpointed sync/async agent replay and deletion, journal restoration, summaries,
delegation snapshots, memory admission and forged Gateway metadata without live
model calls. `contracts/upload_context_contract.json` supplies the same validity
cases to Python and TypeScript tests, including malformed and future metadata.
Existing upload-admission tests continue to exercise owner isolation
through a real agent graph. Frontend coverage pins literal examples, legacy
cleanup, export and conversation grouping; the plain-text Playwright suite checks
the rendered bubble and file chip.
