# Trajectory extension tests

Keep the checkpoint reader in this package. The host has no public checkpoint
reader contract; internal adaptation is centralized in `gateway.py`.

- Run the [local verification commands](README.md#本地验证). CI verifies the
  packaged extension using an isolated wheel installation.
- `tests/trajectory_plugin_gateway.py` is test-only.
  It supplies synthetic identity and a deterministic state-only graph while
  keeping real host ownership checks, checkpoint materialization, SQLite,
  plugin registration and artifact routes. Never mount it in production.
- SQLite reopen tests must close the first saver, open a new connection and
  disable seeding on reopen. Do not replace these with mocked checkpoints.
- Browser tests live in `frontend/tests/e2e/trajectory-plugin.spec.ts`. Preserve
  actual download checks: JSON full text and Markdown ZIP image references.
- New behavior belongs in both focused tests and the relevant CI path filters.
  CI entry points are `.github/workflows/trajectory-plugin-tests.yml` and the
  existing `.github/workflows/e2e-tests.yml`.
- Use temporary data only. Do not read real conversations or commit runtime
  config, local extension installations, browser reports or databases.

Compaction comparisons are lazy, full-text reads of one checkpoint and its
parent, using the same owner ACL and signed cursor as history reads. Keep the
8 MiB/20s bounds and explicit missing-history errors. Preserve message order,
tool arguments/results, previous summary and hidden-message omission counts.
These are snapshot differences, not authoritative model-input mappings. JSON
and Markdown exports include the comparison; browser tests must check content
beyond 4000 characters and desktop/mobile layout.
