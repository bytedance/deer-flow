# Workspace changes runtime invariants

`capture_workspace_snapshot()` participates directly in the run lifecycle, so its cancellation behavior must preserve resource ownership without making unrelated cancellation slower than necessary.

- `include_text=True` creates a temporary `deerflow-workspace-changes-*` text cache. Once `scan_workspace_roots()` has started in `asyncio.to_thread()`, caller cancellation cannot stop that worker. Keep the cache alive until the worker finishes, then remove it before propagating cancellation. Repeated cancellation must not abandon either the drain or cleanup.
- `include_text=False` creates no cache. This path is used by terminal output verification in `runtime/runs/worker.py`; cancellation must propagate promptly instead of waiting for the metadata scan to finish. The still-running scan task must retain a done callback that consumes its eventual result and logs a late failure so no task exception is lost.
- Entering the text-cache drain is intentionally observable at info level because the wait is unbounded by design. A scan failure discovered while draining or after metadata-only cancellation is logged at warning level, while the original `CancelledError` remains the caller-visible outcome.

Regression coverage lives in `backend/tests/blocking_io/test_workspace_changes_recorder.py` and `backend/tests/blocking_io/test_workspace_changes_cancellation.py`.
