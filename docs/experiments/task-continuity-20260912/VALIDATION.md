# Implementation validation

These checks exercise the implementation submitted with the historical experiment.
They are separate from the prototype A/B/C/D quality scores.

| Check | Result |
| --- | --- |
| Backend `make format`, `make lint` | Passed |
| Focused context, authorization, client, sanitization and replay tests | 582 passed |
| Full backend suite on feature | 15,451 passed; 15 failed; 182 skipped; 3 deselected |
| Full backend suite on clean base `4501c76b` | 15,427 passed; the same 15 failed; 182 skipped; 3 deselected |
| New feature's behavioral tests | 24 passed (included above) |
| Published prototype scripts, using the original pinned local fixtures in a temporary copy | 12 passed; no model calls |
| Published per-case metadata versus all five aggregate tables | Matched |
| Final live production-middleware recovery check | 3/3 passed |

The 15 remaining failures have identical test IDs on the clean base and feature;
there are no branch-only failures. They are existing browser/URL-validation/web
fetch tests. This is **not** a green full-suite claim. The complete failure IDs,
source fingerprints and log hashes are in [validation.json](validation.json).
Both worktrees used locked Python dependencies, the same ReadabiliPy JavaScript
dependencies and cached fixture build dependencies. The final suites ran with
local server and dependency access available; the earlier sandbox-restricted
attempt also had unrelated network/permission failures and is not used as the
final comparison.

The live checker uses synthetic history, actual production compaction/continuity
middleware and tools, a real SQLite archive, and graph reconstruction against an
InMemorySaver. It requires model-initiated keyword search, exact source read,
a cited task note and a correct JSON artifact. The summary is deliberately
instructed to omit exact codes; the source lookup strategy is explicitly requested.
It tests recovery mechanics, not spontaneous strategy choice, a process restart,
a Gateway deployment or an end-to-end production success rate.
[Integration protocol and all retained attempt phases](integration/protocol.json)
distinguish the initial network-blocked attempt and the successful iterations.

The default-mode golden SSE replay remains unchanged, and a synchronous graph
executes all three tools. Repeated manual compaction preserves earlier batch
references. Scope, rollback visibility, retention/truncation, cancellation drain,
source validation and authorization are covered by behavioral tests.
