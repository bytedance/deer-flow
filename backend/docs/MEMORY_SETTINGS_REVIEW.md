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

2. Open `Settings > Memory`.

   Default local URLs:
   - App: `http://localhost:2026`
   - Local frontend-only fallback: `http://localhost:3000`

3. Click **Import memory** and select:

   ```text
   backend/docs/memory-settings-sample.json
   ```

   The browser imports the fixture into the currently signed-in user's memory.

## Bulk Local Review

To replace memory for every registered user in a disposable review environment:

```bash
cd backend
uv run python ../scripts/load_memory_sample.py --all-users
```

This command:

- supports SQLite and PostgreSQL registered-user databases;
- creates timestamped backups under `.deer-flow/memory-sample-backups/` before replacing memory;
- imports through the configured memory storage provider; and
- rejects `database.backend: memory`, which has no persistent user registry.

Bulk loading replaces every registered user's memory. Do not run it against an environment containing memory you need to preserve. Pass `--no-backup` only when losing the existing memory is acceptable.

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
- Per-user file-storage target: `backend/.deer-flow/users/{user_id}/memory.json`
- Bulk backups: `backend/.deer-flow/memory-sample-backups/{timestamp}/{user_id}.json`

For an explicit one-file copy, pass `--target PATH` to the loader. There is no implicit target because authenticated sessions use different per-user paths.
