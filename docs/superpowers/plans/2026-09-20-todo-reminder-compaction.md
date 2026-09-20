# Todo Reminder Compaction Implementation Plan

**Goal:** On successful context compaction, exclude old `todo_reminder` messages from both summary input and retained history, preserve `todos`, and let the following TodoMiddleware rebuild current task context when needed.

**Architecture:** Filter generated todo reminder HumanMessages in the shared compaction preparation path after the trigger check and before selecting the retained tail. Both automatic and manual, synchronous and asynchronous callers use this path. Do not mutate input state on a skipped or failed compaction. Reuse TodoMiddleware's existing conditional regeneration instead of introducing a second injector.

**Tech stack:** Python 3.12, LangChain/LangGraph, pytest, Ruff.

## Constraints

- Worktree: `/Users/zhangbubu/.codex/worktrees/todo-reminder-compaction/deer-flow`.
- Base: freshly fetched `origin/main`, `479d2f10c89c054c65882d58957fd9cb37693d21`.
- Branch: `fix/todo-reminder-compaction`.
- The user approved this design in the implementation request. Execute inline without subagents.
- Match the existing `HumanMessage` plus `name="todo_reminder"` identity; do not broadly remove hidden messages, system instructions, or tool-call/result pairs.
- Preserve `state["todos"]`. If `write_todos` remains in context, do not inject a duplicate reminder. An empty todo list needs no reminder.
- Scope excludes refreshing reminders between compactions and rewriting summaries that already contain old reminder text.

## Steps

- [x] Fetch main and create an isolated managed worktree with its own frozen dependency environment.
- [x] Run the required baseline `make test` and `make test-blocking-io`; record unrelated baseline failures separately.
- [x] Add regression tests in `backend/tests/test_todo_compaction.py` for filtering both partitions, sync/async and manual/automatic paths, no-op/failure state preservation, unrelated context preservation, and the compiled graph's next-model request.
- [x] Confirm the new regression tests fail before implementation (10 failed, 6 passed; failures show stale reminders in compaction and the next model request).
- [x] In `DeerFlowSummarizationMiddleware._prepare_compaction`, filter the local message list after trigger evaluation and before cutoff/rescue:

  ```python
  messages = [message for message in messages if not (isinstance(message, HumanMessage) and message.name == "todo_reminder")]
  ```

  Filtering a local list leaves state unchanged until the successful compaction update is applied. Existing no-history handling remains authoritative.
- [x] Confirm a compiled graph with `[summarization, TodoMiddleware()]` keeps `todos`, rebuilds exactly one reminder with current task statuses when `write_todos` was compacted, and sends it to the next model. Confirm no regeneration for empty todos or a retained `write_todos` call.
- [x] Document the behavior in `README.md` and the middleware `AGENTS.md`.
- [x] Run focused tests, Ruff checks/formatting, and both required offline targets after the change. Compare any broad-suite failures with baseline results.
- [x] Review the diff and preserve the completed work on `fix/todo-reminder-compaction` in the requested worktree.

## Validation results

- Baseline `make test`: 17,701 passed, 202 skipped, 3 deselected, 4 failed in 1254.74s. The four pre-existing failures are in `test_extension_manager.py`; their uv subprocesses time out requesting `https://pypi.org/simple/deerflow-extension-demo/` before reaching the expected build-context validation.
- Baseline `make test-blocking-io`: 149 passed.
- Focused post-change suite: `uv run pytest tests/test_todo_compaction.py tests/test_summarization_middleware.py tests/test_todo_middleware.py -q --tb=short` — 126 passed.
- Ruff check and format check: both changed Python files pass.
- Post-change `make test`: **17,721 passed, 202 skipped, 3 deselected** in 510.15s. All four baseline extension-installation timeout failures passed on this run; there are no remaining failures.
- Post-change `make test-blocking-io`: **149 passed** in 9.40s.
- `git diff --check` passes; the new regression tests need no external APIs/models.
- Review confirmed the production change uses a local filtered list, preserves system/dynamic context and complete tool pairs, and leaves TodoMiddleware's existing regeneration and completion logic intact.
