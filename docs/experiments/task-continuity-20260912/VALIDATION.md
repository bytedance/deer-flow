# Implementation validation

These checks exercise the implementation and review fixes. They are separate
from the historical prototype A/B/C/D quality scores.

## Latest follow-up: review 5185922053

Malformed history metadata is validated by all four consuming sites, including
capture failure recovery and durable-context rendering. Existing bad checkpoints
can continue before compaction; a successful capture repairs their metadata.
SQLite captures now serialize retention decisions and evict before inserting a
replacement in the same transaction. Failed replacements preserve old sources;
duplicate capture also retains the right reference when retention is reduced.

The initial regressions had **13 failures and 57 passing controls**. After the
fix and additional transaction/concurrency controls, **270 focused tests pass**
(including 78 continuity tests); format, lint and diff checks pass. Full backend:
**15,520 passed, 15 failed, 182 skipped, 3 deselected**. The 15 failure IDs
match the earlier full clean-base result and a fresh rerun of all those IDs on
the unchanged clean base. There are no branch-only failures.

Capacity tests use a real SQLite database with a scaled 1024-page ceiling;
the production ceiling remains 32768 pages. An isolated autocommit mutation
fails the old-source preservation assertion after `SQLITE_FULL`, confirming the
rollback check observes persisted data. Two gated writer threads cover both
distinct and duplicate batches. The guide checker reports no errors and the
existing chain-size soft warning. No live model experiment was rerun.

The previous remote shard-3 failure occurred in `Install uv` (`fetch failed`);
dependency installation and unit tests were skipped. It provides no test-failure
evidence against this implementation. Remote results for the follow-up commit
are tracked separately on the PR.
[Follow-up metadata and source/log hashes](review3-validation.json).

## Earlier follow-up: review 5185827206

The second review at `fac6a37e` exposed mixed-content extraction and missing
release-policy declarations. The regressions produced **20 failures before the
fix**, with 83 controls passing. After the fix, **249 focused tests pass**,
including sync/async graph compaction and checkpoint reconstruction, exact source
search/read, and per-field assembly fingerprint checks. Format and lint pass.

The new full backend run has **15,499 passed, 15 failed, 182 skipped and
3 deselected**. Its failure IDs exactly match the earlier clean-base full run
below; all 15 were also rerun and failed on the unchanged clean base this round.
There are no branch-only failures. A filter-removal negative control confirms
the serializer test rejects reasoning/image/unknown text entering the archive.
The guide checker has no errors and one existing chain-size soft warning.

The extraction boundary is plain strings plus `type: text` blocks, in original
order, for both active lookup and archive capture. The identity boundary covers
all four continuity configuration fields and all three DurableContext constructor
settings; normalized equivalent and disabled configurations remain equivalent.
The live model and historical prototype results below belong to the earlier
validation phase and were not rerun for this follow-up.
[Follow-up metadata and source/log hashes](review2-validation.json).

## Earlier validation before the second review

| Check | Result |
| --- | --- |
| Backend `make format`, `make lint` | Passed |
| Focused continuity, Gateway state/run input and reducer tests | 370 passed |
| Full backend suite on feature | 15,474 passed; 15 failed; 182 skipped; 3 deselected |
| Full backend suite on clean base `4501c76b` | 15,427 passed; the same 15 failed; 182 skipped; 3 deselected |
| Feature behavioral tests | 43 passed (included above) |
| Published prototype scripts, with pinned local fixtures in a temporary copy | 14 passed; no model calls |
| Published per-case metadata versus all five aggregate tables | Matched; scores unchanged |
| Live production-middleware recovery check after review fixes | 3/3 passed |
| Real config-upgrade script on temporary version-41 configs | Upgraded to 42; default disabled and explicit enabled both preserved |
| Helm lint, template render, sandbox/ingress checks and config-version alignment | Passed; rendered task continuity remains disabled by default |

The 15 remaining failures have identical test IDs on the clean base and feature;
there are no branch-only failures. They are existing browser/URL-validation/web
fetch tests. This is **not** a green full-suite claim. Complete failure IDs,
source fingerprints and log hashes are in [validation.json](validation.json).
Both worktrees used locked Python dependencies and had local test-server and
dependency access available.

## Review regressions

On the reviewed commit `aee9a537`, the targeted checks produced 22 backend failures
and two audit failures, with the foreign-scope negative control passing. After
fixing them, the first full run identified one stale expected reducer-field list;
that existing contract test was updated for `task_notes` and the full suite rerun.
The intermediate full-run records are retained in the validation metadata.
Additional regressions exposed direct Overwrite and first-write deletion-marker
gaps; both failed before validation moved into the shared state channel and
pass in the final implementation.

The final behavioral checks cover:

- Hidden clarification text/option replies: compact, search and read the exact
  user-approved value without relying on active-message fallback; hidden
  framework messages and malformed reply metadata remain excluded.
- Explicit disabled configurations in both sync and async middleware paths.
- Capture-failure status with no prior archive, an empty matching scope, old
  readable sources, and a foreign scope that must remain isolated.
- Notebook limits and model-report shape in the shared state channel, including
  initial writes, direct Overwrite and reducer updates, plus defensive rendering;
  deletion operations do not leave initial tombstones in checkpoints.
- Full/delta checkpoint state replacement through both introspection and fallback,
  and branch creation that clears archive scope/status while retaining notes.
- Artifact scanning of optional LLM credentials and absent/null/empty settings.

The live checker uses synthetic history, actual production compaction/continuity
middleware and tools, a real SQLite archive, and graph reconstruction against an
InMemorySaver. It requires model-initiated keyword search, exact source read,
a cited task note and a correct JSON artifact. The summary deliberately omits
exact codes and the source lookup strategy is explicitly requested. These are
controlled recovery mechanics, not spontaneous strategy choice, a process
restart, a Gateway deployment or a production success rate. The three existing
live cases were rerun after the fixes; clarification-card cases are covered by
the deterministic compaction regressions above.
[Integration protocol and retained phases](integration/protocol.json) distinguish
the earlier attempts from [the review rerun](integration/review-network.json).

The original successful A/B/C/D model samples were not regenerated. The replay
suite now includes two artifact-audit regressions; its original 12 tests and the
historical experiment scores remain intact.

The first remote chart check caught an omitted version alignment: the root
example was 42 while the chart still embedded 41. The chart values and README
example now both use 42. All five local chart checks passed, and the rendered
configuration retains disabled task-continuity defaults. This follow-up changes
chart metadata and validation records; the backend code and test fingerprints
above are unchanged.
