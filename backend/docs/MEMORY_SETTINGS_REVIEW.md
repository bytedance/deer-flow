# Memory Settings Review

Use this when reviewing the Memory Settings search, filter, delete, and clear-all flow locally.

## Quick Review

1. Start DeerFlow locally.

   ```bash
   make dev
   ```

2. Load the sample memory fixture.

   ```bash
   python scripts/load_memory_sample.py
   ```

3. Open the app and review `Settings > Memory`.

   Default local URLs:
   - App: `http://localhost:2026`
   - Local frontend-only fallback: `http://localhost:3000`

## What To Check

- Search `memory` and confirm multiple facts are matched.
- Search `Chinese` and confirm text filtering works.
- Search `workflow` and confirm category text is also searchable.
- Switch between `All`, `Facts`, and `Summaries`.
- Delete the disposable sample fact and confirm the list updates immediately.
- Clear all memory and confirm the page enters the empty state.

## Fixture Files

- Sample fixture: `backend/docs/memory-settings-sample.json`
- Default local runtime target: `backend/.deer-flow/memory.json`

The loader script creates a timestamped backup automatically before overwriting an existing runtime memory file.
