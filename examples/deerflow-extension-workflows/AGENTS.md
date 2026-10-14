# Script workflow extension

Keep workflow business logic in this packaged extension. Import only public
`deerflow_extension_api` contracts, standard library and declared QuickJS dependency;
never import private `app.*` or `deerflow.*` runtime modules.

Generated script runs only in worker.py's isolated, capability-free JS context.
Never pass host callables, capability handles, credentials or ambient environment
into it. Keep every IPC and stored/public payload bounded. Parent lifecycle must
kill and reap the worker and explicitly observe child cancellation.

Persist stable child thread, input message, attempt and idempotency identity before
admission. Workflow cancel is a supervisor signal; do not cancel an admission task
and lose an already-created child. Timeout/unknown outcomes require reconciliation,
never automatic retries. Distinguish admission uncertainty from post-admission
observation timeout: interrupt/observe known runs and escalate only uncertain cleanup.
Keep the workflow deadline handler outside asyncio.timeout and test external cancellation
separately. Hash the Agent allowlist in canonical sorted order. Owner scope applies
to every public read and mutation.
Own persistence through supervisor publication even if the launching caller cancels.
Serialize launch admission and shutdown. Hold the process lock across service life;
do not recover live records while another Gateway owns the file.

Anchor results on the visible human input, including canonical __user rewrites;
never use hidden system/memory IDs. Retain UI launch identity across refresh failures.
Thread latest state is not immutable run output. Check message/run attribution,
interrupts and pending human input before copying output. Agent success is never
human approval. Phase 1 has no resume, artifact approval, effective-configuration
fingerprint guarantee, cross-process replay or hard monetary budget; keep limitations
visible in docs, tool descriptions and UI. Do not serialize capability handles.

Tests live in backend/tests/test_workflow_plugin.py. Run the backend offline and
blocking-I/O targets plus verify_browser.mjs. The browser fixture is loopback-only
and synthetic; it must never become a deployed authentication bypass.
