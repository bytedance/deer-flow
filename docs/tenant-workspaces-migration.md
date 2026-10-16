# Tenant metadata attribution and migration receipts

Status: offline attribution foundation implemented. This is not an approved
production rollout. Tenant authorization, NAS mapping and schema-aware release
acceptance remain pending. Historical `0035/e0001` release receipts are immutable.

## Scope and prerequisites

`scripts/tenant_migration.py` operates only on native `0039_run_workspace_identity`
and independent executor `e0002_workspace_scope` databases. It never performs
DDL, starts workers, enables registration, resumes admission, releases physical
capacity or changes account verification. M10 must collect actual drain,
physical-stop, coherent backup/restore and NAS evidence and own the schema
upgrade sequence. The CLI cannot generate those operational proofs itself.

Use the installed backend/executor environment in Shanghai Jenkins. Set
`DEERFLOW_TENANT_NATIVE_URL` and `DEERFLOW_TENANT_EXECUTOR_URL` through private
Jenkins configuration; never put URLs or keys in command arguments. The receipt
directory must be owned by the executing operator, exactly mode 0700, outside
the checkout. JSON inputs and outputs are owned regular mode-0600 files; symlink
files are refused. Restrict access to the directory: plans contain resource IDs.

The target fingerprint is a SHA-256 binding of both database locations and
connection query options. Credentials are not emitted or stored in receipts.
Two separate persistent SQLite files or independent PostgreSQL databases are
required. Source databases must remain stopped/fenced across both phases.

## Commands and order

Run these commands in the configured cloud backend environment. The example
receipt directory `/data/deerflow-private/tenant-migration` must already exist
with the ownership/modes above and a reviewed maintenance evidence package.

```bash
python scripts/tenant_migration.py plan --phase native --receipt-directory /data/deerflow-private/tenant-migration
python scripts/tenant_migration.py apply --phase native --receipt-directory /data/deerflow-private/tenant-migration
python scripts/tenant_migration.py plan --phase executor --receipt-directory /data/deerflow-private/tenant-migration
python scripts/tenant_migration.py apply --phase executor --receipt-directory /data/deerflow-private/tenant-migration
python scripts/tenant_migration.py verify --phase all --receipt-directory /data/deerflow-private/tenant-migration
```

Native plan reads metadata without database writes and saves a private uniquely
named `plan-*.json`. Every apply and final verify requires fresh evidence.
Executor planning also requires the completed native receipt and matching live
native export. Public command output contains only operation, phase and status.
Failures withhold driver errors and private configuration; exit status is 1.

## Evidence input contract

The trusted operator's collector supplies `maintenance.json`. It is not an
API input or tenant-controlled file. Synthetic test receipts must never be used
as cloud evidence. M10 must validate the collectors against actual processes,
backup artifacts and a successful isolated restore before publishing a package.

| Maintenance field | Required value |
| --- | --- |
| format | `deerflow.tenant.maintenance.v1` |
| generation | Canonical UUID for this stopped-writer/backup generation |
| target_sha256 | `target_fingerprint(native_engine, executor_engine)` for the exact targets |
| expires_at | Aware ISO timestamp in the future, at most 24 hours from the check |
| evidence | Exactly `drain` and `backup`, each with a local basename `file` and raw-file SHA-256 `sha256` |

Both referenced JSON files must have the same generation and target_sha256.
The drain receipt format is `deerflow.tenant.drain.v1`, with
`admission_closed`, `writers_stopped`, and `physical_stopped` all exactly true.
The backup receipt format is `deerflow.tenant.backup.v1`, with
`restore_verified` exactly true and pinned SHA-256 fields `native_sha256`,
`executor_sha256`, and `nas_manifest_sha256`. False/missing flags, missing or
changed files, wrong bindings and expired packages are refused before writes.
Hash and field checks validate the trusted package's integrity; they do not
observe live hosts or prove a restore independently of the collector.

Do not edit a completed package to extend its expiry. A new maintenance
generation requires renewed operational evidence and a new private directory.
The database attribution itself remains idempotent.

## Phase outputs and interruption recovery

`native.json` records the exact target, generation, maintenance digest, both
schema revisions, native result, private ownership export and its SHA-256,
and a post-apply native ownership-plan digest. Export contains only matching
user/thread/incarnation/run identities; orphan/conflicting resources are omitted.
`executor.json` records the same binding, export digest and executor result.
Only top-level job scope and its indexed column are assigned; original native
snapshot, job version, physical state and affinity node remain unchanged.

The CLI serializes its local operation with a private nonblocking file lock,
uses each database's maintenance transaction and fsyncs exclusive phase files.
It does not claim a transaction spanning both databases. A committed native
phase without an executor receipt is incomplete and verify refuses it.

Re-run the same explicit apply phase after an interruption. If its complete
receipt exists, the CLI checks current metadata against it and returns the
existing receipt without replay. If database commit finished before its receipt
was created, idempotent attribution can complete that receipt. A torn JSON file,
changed ownership, conflicting evidence or expired maintenance requires operator
review; the CLI never silently deletes, overwrites or repairs evidence.

Successful verify reports `metadata_verified: true` and always
`ready_for_activation: false`. Unknown/conflicting records remain quarantined;
their private identifiers are retained in receipts. NAS mapping, live tenant
authorization and schema-aware release gates are still required. No image-only
rollback or data deletion is offered by this command.

## Current evidence

`backend/tests/test_tenant_migration_cli.py` uses real SQLite and independent
PostgreSQL databases. Its maintenance inputs are explicitly synthetic consumer
contract fixtures, not operational drain/backup proof. It verifies refusal
before writes, phase ordering, incomplete verification, repeat execution,
quarantine retention, evidence tampering, and actual CLI plan invocation.
Exact source digests and Jenkins results are in
[implementation progress](tenant-workspaces-progress.json).


Project visibility refinement: `0037_project_visibility` follows the unchanged
`0036_tenant_workspaces`; existing projects receive private visibility, never an
automatic team grant. At that checkpoint, native startup and both sides of the offline ownership
export agreed on 0037. The later 0038 and current 0039 requirements are recorded below. Previous 0036 phase receipts remain historical
and cannot be reused for the new generation. The executor stays at e0002.
Jenkins #23 verified real 0035-to-current upgrades on both databases plus paired
attribution; #24 verified the actual plan/apply/verify CLI and synthetic receipt
requirements on both. These are consumer/DDL proofs, not cloud drain, restored
production backups, NAS mapping or deployed tenant release acceptance.

Read-clock revision `0038_workspace_read_clocks` was appended after unchanged
0037. It adds `workspace_thread_read_versions` keyed by `(workspace_id,user_id)`
with a BIGINT zero-default clock. Native per-user clocks/markers and shipped
ancestors are unchanged. DDL does not copy a global clock into team spaces or
attribute ownership. New workspace clocks begin at zero and advance only with
a scoped marker change. Native backfill/export and independent executor import
at that checkpoint required the reviewed 0038 revision; old receipts remain immutable and cannot
stand in for a matching new generation. Executor e0002 is unchanged.


Current native head is `0039_run_workspace_identity`, following unchanged 0038.
It adds nullable JSON `runs.workspace_context_json` (the immutable four-field
identity) and nullable VARCHAR(32) `runs.thread_incarnation`. Fresh ORM and parent
upgrade share this shape. Historical rows keep their prior bytes/ownership and
receive no permission snapshot or incarnation grant. Repeated upgrades are
idempotent; destructive downgrade refuses, requiring a matched backup instead.
Current native backfill/export and independent executor import require 0039 and
e0002. Past deployment receipts remain immutable. M10 must align the complete
candidate's startup schema fence and paired release manifest before activation;
the existing closed startup fence is not an activation proof.

The original workspace snapshot is captured at private thread admission, not
from client metadata or current UI selection at recovery. Snapshot equality is
identity only, not current membership authorization. Ordinary Agent Run and
worker lifecycle integration, revocation, live publish/continuation checks and
physical release/restore still remain M4/M10 acceptance work.
