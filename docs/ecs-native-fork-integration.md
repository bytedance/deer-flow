# Audited native user-fork integration and schema boundary

Task6A content was reviewed against native `5164c6fc` and committed as `dce5d110`. Root subsequently integrated cached user-fork history through reviewed two-parent merge `ebda3727`, retaining that exact native content tree. This is not production activation. Cached fork `96bacf4f42ee1ae24ab988cc369e0720c65f0bd5`, Gitee `a816a744fa8ded80a638c1262384cd2f72124751`, and ancestor `c35022e18bead8aa35020f2ffa31f28dd2ac4622` were read locally. Remote heads were not refreshed. Official origin is never a push target. Disabled Actions preference and previous comparison worktrees/branches remain untouched.

## Content and behavior disposition

[The manifest](ecs-native-fork-disposition.v1.json) enumerates all **559** cached fork delta paths, with source/native-before blob IDs, disposition, behavior and replacement. `python scripts/audit_native_fork.py` checks complete coverage, no duplicates, cached blobs and exact retained template bytes. Path coverage is not a claim that historical Fleet behavior remains active.

| Disposition | Count | Meaning |
| --- | ---: | --- |
| retained_exact | 1 | Gitee pull request template, copied exactly |
| adapted | 15 | Docker dev wiring/docs, three historical revisions, unrelated fixture isolation and MCP runtime preservation, reversible native-branch DDL tests |
| replaced | 256 | Current native authority, config/contracts and ordinary frontend replace rejected Fleet integrations |
| retired | 287 | Old routes, fixtures, deployment helpers, authority and historical acceptance docs remain in immutable fork history |

The unrelated adaptations preserve `0aee7096` host/container database guidance; owned Docker cleanup without inherited container CLI; PostgreSQL Delta schema/reopen isolation and DSN handling; inherited `UV_NO_SYNC` removal; plain PostgreSQL URL normalization to asyncpg; and actual local MCP Runtime injection. Current upstream test bodies remain outside those narrow changes. Old docs/`IMPLEMENTED` markers are historical, not native acceptance.

Old `/agent-tasks` PAT read/cancel/resume rights are retired with their routes. Existing native Run/goal APIs keep native scopes and ownership; old PAT users need the native API/scope, without automatic privilege conversion. Old worker-local channel-human signatures/Fleet generation mutation and appended Fleet summaries are retired. Native owner/internal-token admission and Run/goal checks remain authoritative. Old signatures never grant new intent. Old Fleet cross-run task budget/generation tables and counters are not converted. Current trusted core seams are deliberate fork contracts, not a fully portable public plugin.

The cached local persistent ToolNode regression reproduced `runtime=None` in an interceptor. Concrete hidden `Runtime` annotations now preserve server identity for persistent/background adapters; the regression supplies a valid native incarnation. Public model schema is unchanged, no native incarnation guard is weakened, and no old Fleet mutation/workspace plumbing is imported.

Root completed local history integration after fresh SPEC/quality PASS: reviewed two-parent merge `ebda37276a3456d84d120bae885113b6581f936a` has parents `dce5d110eeb2b4566414adc147734722e9400fb4` and cached fork `96bacf4f42ee1ae24ab988cc369e0720c65f0bd5`. Its tree is byte-identical to reviewed native content; the cached Gitee head is also an ancestor. The manifest records rejected/replaced Fleet content and the fork parent preserves history. Do not use an unaudited `-s ours`, wholesale fork checkout, or silently reset a fork branch. Future publishing must compare refreshed user heads and preserve newer deltas; this manifest covers cached refs only. The implementer did not stage or commit. Root saved the reviewed local content and history as recorded above; no fetch, push or PR occurred.

## Real schema upgrade versus legacy activation quarantine

Integrated head `0035_native_fork_compatibility` joins native `0034_run_event_seq_watermark` and exact historical `0022_fleet_main_merge`. Historical `0018_thread_execution_bindings` retains parent `0017_personal_access_tokens`; `0019_scheduled_execution` remains its child; `0022` retains `(0019_scheduled_execution, 0019_thread_incarnations)`. No shipped native ancestor was reparented. Real upgrades retain binding rows and opaque schedule execution JSON. Protected downgrade refuses deletion; stamping is not an upgrade.

Immediately after native DB initialization, before checkpoint/recovery/scheduler activation, Gateway refuses any legacy binding, non-NULL schedule execution JSON or `fleet_*` table. This whole-database activation quarantine has no bypass flag, auto-replay, local fallback, permission expansion, automatic conversion or new authority table. Fresh/native databases without legacy intent activate normally. Autogenerate excludes historical intent from deletion. Fresh real Alembic upgrades create empty historical structures; native empty-ORM hybrid bootstrap need not create unused historical structures. Both have no legacy intent to replay.

### Inventory, drain and backup

Stop old admission and scheduling, drain old workers, and verify physical containers stopped. Preserve uncertain reservations until actual STOP; old and new dispatchers must never run together. Record source/image versions, native/Fleet migration heads, private config references and NAS identity. After all writers stop, take coherent native/Fleet DB and NAS backups and verify restore into an owned separate copy.

Supply a private synchronous SQLAlchemy URL (such as `postgresql+psycopg`) through the named env variable, without printing it:

```bash
cd backend
PYTHONPATH=.:packages/ecs-executor .venv/bin/python \
  -m deerflow.persistence.legacy_execution \
  --database-url-env DEERFLOW_LEGACY_INVENTORY_DATABASE_URL
```

The read-only report contains binding/task IDs, statuses, active native runs/occurrences, and legacy table names/counts. It excludes raw intent/workspace JSON, credentials and URLs. Check active counts before/after draining; database status alone does not prove physical STOP. Empty old Fleet tables also quarantine activation conservatively. Inventory never acknowledges or converts intent. **Do not clear JSON or delete bindings to unlock startup.** Continuing old execution requires separately reviewed explicit disposition; that remains pending if historical continuation is required.

Run an offline native upgrade only on a stopped backup copy using its private asyncpg URL:

```bash
cd backend
PYTHONPATH=. .venv/bin/python - <<'PY'
import asyncio, os
from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine
from deerflow.persistence.bootstrap import _get_alembic_config
async def upgrade():
    engine = create_async_engine(os.environ["DEERFLOW_OFFLINE_DATABASE_URL"])
    try:
        await asyncio.to_thread(command.upgrade, _get_alembic_config(engine), "head")
        print("Offline schema upgraded; activation still requires inventory")
    except Exception:
        raise SystemExit("Offline schema upgrade refused (URL withheld)") from None
    finally:
        await engine.dispose()
asyncio.run(upgrade())
PY
```

For a custom PostgreSQL schema, create/restore that schema first and supply its validated name as `postgres_schema` to `_get_alembic_config`, with matching `build_asyncpg_connect_args(schema)` on the engine. Never migrate under a different search_path. This executes ancestry, never stamp-as-migration, and does not activate Gateway.

### Reversible fresh-database cutover

Keep the stopped old deployment and complete DB/NAS backup intact. Provision a fresh native DB and an independent executor DB, configure their new identities and a deliberately selected NAS workspace. Do not use old Fleet workspace state as new execution state. Apply/check schemas, inventory no legacy intent, then activate the reviewed native binary. Historical conversations remain in the old backup/deployment until an explicit import/disposition is reviewed. This route preserves data but does not continue historical execution.

Rollback first stops/drains new admissions and physical jobs. Restore the coherent pre-cutover native/Fleet DB+NAS backup, select recorded old binary/config references, and start only the old deployment. Keep new DB/NAS separately for audit. Never run destructive Alembic downgrade or point old binaries at newer executor schemas. Exact supervised startup/image rollback and cgroup/cloud acceptance remain Task6B.

## Independently versioned executor

The dedicated executor DB contains only `ecs_execution_jobs`, `ecs_execution_nodes`, `ecs_native_affinities`, and `ecs_executor_alembic_version`, with no native/Fleet tables or other application schemas. Native Run/MCP/schedules/checkpoints keep native ownership. Publication `metadata_database_url` names native metadata, never the executor DB.

Private `e0001_execution_ledger` creates missing known tables and adopts only exact accepted unversioned column/key/index/default/generated/FK/CHECK/collation semantics. It preserves every record/version/state, including unknown reservations and ambiguous starts, without claims, release or replay. Unknown shape/version fails closed. PostgreSQL transactional advisory locking serializes explicit upgrades. Before upgrade, stop B service, central and outbound workers; drain/inventory physical reservations and back up the matching executor/native DB/NAS generation. Provide the private executor URL in `ECS_EXECUTOR_DATABASE_URL`:

```bash
cd backend
PYTHONPATH=.:packages/ecs-executor .venv/bin/python -m ecs_executor.schema upgrade
PYTHONPATH=.:packages/ecs-executor .venv/bin/python -m ecs_executor.schema check
```

B/central startup only call read-only `require_schema`. Outbound B/native workers send/check that revision over existing authenticated node credentials and mount/protocol checks; arbitrary unauthenticated reports cannot grant compatibility. Missing revision is incompatible. `JobStore.initialize()` is an explicit Python local/test helper executing the versioned path; no production flag selects bootstrap. No new Agent, goal, notification, relay or legacy authority tables were introduced.

## Local evidence and boundaries

| Check | Actual result |
| --- | --- |
| Initial schema/graph/quarantine RED → GREEN | 4 intended failures → 4 passed |
| Owned PostgreSQL16 fresh/native0034/Fleet0022 ancestry main | 9 passed; one0035 head, native event/binding/opaque schedule JSON preserved, old activation denied and native/fresh allowed |
| Remaining owned PostgreSQL executor/autogenerate/Delta reopen checks | 3 passed; uncertain version11 reservation unchanged and owned saver schema retained |
| Guards/B/scheduler focused invocation | 22 passed,4 skipped before separate PG run; existing MCP deprecation warning |
| Adapted owned Docker/Delta fixtures without PG URL | 21 passed,11 skipped |
| Directly affected reversible native DDL tests | 5 passed after branch isolation |
| Final focused schema/C/BC/dispatch/local MCP + affected migration/filter invocation | 66 passed,8 skipped (live/PG opt-ins absent) |
| Remaining historical head assertions | 5 passed,3 skipped (PG opt-in absent) |
| Ordinary MCP wrapping/sync and adapted Docker/Delta fixtures | 43 passed,11 skipped (PG opt-in absent) |
| Changed Python formatting/lint and whitespace | 33 files clean; git diff --check clean |

Commands use the existing locked `.venv`, `PYTHONPATH=.:packages/ecs-executor`, `--no-showlocals --tb=short`. Owned UUID PostgreSQL containers were removed. Live C/BC/browser/shared-pool helpers now provision distinct owned DBs and explicitly upgrade executor schema; native observation and metadata publication use native URLs. Previous model evidence remains historical; no model rerun was used for this wiring correction.

No user database, private key/config/env, model execution, ECS, SSH, Jenkins, fetch/push/PR or deployment was used. Final whole-backend and blocking-I/O gates, supervised operations/cgroups/Nginx/WebSocket/version rollback and Shanghai cloud acceptance remain Task6B. Task6 and the overall objective remain incomplete.

The remaining operational zero-model startup/image gate must exercise the revised separate-DB live helper wiring under Task6B; static/source and focused regression checks here do not claim an installed C/BC/browser rerun.


### Task6A SPEC correction evidence

The SPEC review reproduced two real gaps. An unversioned SQLite ledger carrying
`CHECK(version <= 1)` or an additional `UNIQUE(state)` was initially adopted even
though ordinary writes would fail later. Both now fail compatibility admission
without changing the retained row or creating a version stamp. Validation freezes
column types/nullability/defaults/generated values, primary/unique keys, foreign
keys, CHECK constraints and index shape/semantics for ledger and version tables.
No unknown constraint/index is dropped or repaired.

The first strict PostgreSQL recheck rejected the accepted schema because
SQLAlchemy exposes neutral UNIQUE reflection metadata. Only empty INCLUDE and
default false/null NULLS NOT DISTINCT metadata are normalized; non-neutral
variants remain denied. The same single owned PostgreSQL executor-adoption case
then passed (**1 passed**), preserving the uncertain version11 row. That container
was removed; the nine-case ancestry main and model scenarios were not repeated.

Both CLI env lookups and engine construction now occur inside redacted exception
handling, and disposal runs only for initialized engines. Synthetic malformed-port
markers previously appeared in stderr; both CLI regressions now exclude the
marker and report only the redacted failure. Their child environments contain
only public package paths and synthetic URL data, with no private env copy.

Corrected focused invocation, from `backend/`:

```bash
PYTHONPATH=.:packages/ecs-executor .venv/bin/python -m pytest \
  tests/test_ecs_schema_compatibility.py tests/test_ecs_executor_b_main.py \
  -q --no-showlocals --tb=short -p no:cacheprovider
```

Result: **22 passed,5 skipped**, one pre-existing MCP deprecation warning. The
CHECK/UNIQUE and malformed-URL cases were observed failing before correction.
Changed-file formatting/lint and the revised47-file hash freeze are recorded
for the same SPEC recheck; no broad gate, model, deployment or user DB was used.

### Task6A quality correction evidence

The quality review reproduced a SQLite request identity collision: an otherwise
accepted unversioned ledger with `request_key VARCHAR(128) COLLATE NOCASE` passed
adoption and startup checks. The focused regression first failed with `DID NOT
RAISE`; admission now refuses it before any version stamp while retaining the
original row. SQLite native generated DDL has no explicit `COLLATE`; admission
conservatively rejects any explicit override and checks actual `index_xinfo`
collations for native BINARY semantics. No collation is repaired or dropped.
PostgreSQL admission checks catalog column collations against the native type
default because ordinary column reflection omits overrides.

The same schema/B focused command above now reports **23 passed,5 skipped**, with
one pre-existing MCP deprecation warning. The existing owned PostgreSQL
executor-adoption case passed (**1 passed**), preserving its uncertain version11
reservation under the new catalog check; its container was removed. This was
only a narrow check of the newly introduced PostgreSQL reflection risk, with no
ancestry, model, broad gate, deployment or user database repeat.

## Reviewed local integration record

SPEC and quality rechecks passed after constraint/index, CLI redaction and collation fixes. Root independently verified six critical scope/quarantine/CLI/schema regressions (6 passed,2.02s) and the collation regression (1 passed,0.88s). All47 reviewed hashes matched before content commit. The history merge changed no file bytes and a clean worktree plus both cached user-head ancestry checks passed. Full installed startup and final whole-backend/blocking-I/O gates remain Task6B.
