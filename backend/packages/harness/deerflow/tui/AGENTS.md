# Terminal UI (`deerflow/tui/`)

The `deerflow` console script: a terminal UI and headless `--print` / `--json`
modes over `DeerFlowClient`. It is a shell over the embedded client and does not
change agent behavior. User guide: [docs/TUI.md](../../../../docs/TUI.md).

## Verify

```bash
cd backend
python -m pytest tests -q -k "tui"
```

Every layer except `app.py` and `widgets/` is free of Textual and is tested with
plain pytest. The app is tested through Textual's pilot with a fake session.

## Structure

- **Keep logic in the pure layers.** `view_state.reduce` and `runtime.translate`
  hold the behavior; `app.py` marshals actions to the UI thread.
- **Keep the client import lazy in `cli.py`**, so help and launch planning do not
  load the agent stack. `textual` is optional, and the script falls back to
  headless help without it.
- **An assistant delta is appended as given.** The client sends incremental text
  only, so a delta that repeats the row's ending is new text, not a resend.
- **A provider failure arrives as a flagged message, not an exception.** The
  headless modes exit with status 1 on it.
- **The command registry excludes the slash names that the agent runtime
  reserves**, in the picker and in the resolver.

## Runs and threads

- **Reserve the run identity and the busy state when input is accepted**, before
  the worker starts. Each run owns its cancellation flag. If the worker cannot
  start, clear the reservation and give the text back to the composer.
- **A worker callback checks the run identity and the thread ID on delivery.** A
  cancelled, finished or superseded run must not update the view.
- **An interrupted worker streams until its next event, so a long tool step still
  checkpoints.** Until it returns, reject a send on its thread: the run that
  checkpoints last would drop the other turn.
- **Reject a thread switch during a run twice**: before the picker opens, and
  when its callback applies, because the callback can outlive the idle state.
- **Run workers are daemon threads, not Textual thread workers.** Asyncio's
  default executor is joined when the app exits, and quitting would hang until
  the step ended.
- **A finished run still writes its title to its own thread** after the UI has
  moved on. Keep that write off the UI thread.

## Web UI visibility

- **`persistence.py` writes a `threads_meta` row for the default user**, because
  the Web UI lists threads from that table and not from the checkpointer. The
  write is best effort.
- **All database work runs on one long-lived background loop.** A SQLAlchemy
  async engine is bound to the loop that created it.
- **A bridge timeout requests cooperative cancellation.** It does not roll back a
  committed write.

## Composer

- **Slash arguments keep their whitespace.** A skill submission keeps its line
  breaks and indentation.
- **When history returns `None`, leave the composer untouched**, including its
  cursor and undo state. An empty string is a valid saved draft.
