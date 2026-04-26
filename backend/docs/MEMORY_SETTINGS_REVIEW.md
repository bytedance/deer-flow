# Memory Settings Review

Use this when reviewing the Memory Settings add/edit flow locally with the fewest possible manual steps.

## Quick Review

1. Start DeerFlow locally using any working development setup you already use.

   Examples:

   ```bash
   make dev
   ```

   or

   ```bash
   make docker-start
   ```

   If you already have DeerFlow running locally, you can reuse that existing setup.

2. Load the sample memory fixture.

   ```bash
   python scripts/load_memory_sample.py
   ```

3. Open `Settings > Memory`.

   Default local URLs:
   - App: `http://localhost:2026`
   - Local frontend-only fallback: `http://localhost:3000`

## Minimal Manual Test

1. Click `Add fact`.
2. Create a new fact with:
   - Content: `Reviewer-added memory fact`
   - Category: `testing`
   - Confidence: `0.88`
3. Confirm the new fact appears immediately and shows `Manual` as the source.
4. Edit the sample fact `This sample fact is intended for edit testing.` and change it to:
   - Content: `This sample fact was edited during manual review.`
   - Category: `testing`
   - Confidence: `0.91`
5. Confirm the edited fact updates immediately.
6. Refresh the page and confirm both the newly added fact and the edited fact still persist.

## Optional Sanity Checks

- Search `Reviewer-added` and confirm the new fact is matched.
- Search `workflow` and confirm category text is searchable.
- Switch between `All`, `Facts`, and `Summaries`.
- Delete the disposable sample fact `Delete fact testing can target this disposable sample entry.` and confirm the list updates immediately.
- Clear all memory and confirm the page enters the empty state.

## Fixture Files

- Sample fixture: `backend/docs/memory-settings-sample.json`
- Default local runtime target: `backend/.deer-flow/memory.json`

The loader script creates a timestamped backup automatically before overwriting an existing runtime memory file.
