# Skill evolution host API (P0)

DeerFlow supplies evidence, versioned candidate staging, checking, publication,
and recovery. The learning strategy, candidate generation, quality evaluation,
and product UI belong to the extension and are not included in this feature.

## Enable deliberately

Use `deerflow-extension-api==0.2.6`. Existing extensions need no changes: both
`ExtensionRuntimeDeps.completed_run_evidence` and `.skill_mutations` default to
`None`. The older cross-user `run_evidence_reader` is unchanged.

Automatic publication requires:

- A durable application database (`sqlite` or `postgres`) and `run_events.backend: db`.
- One POSIX host and shared **local** skill storage. NFS, CSI, and multi-node
  deployments are unsupported, including when the database is PostgreSQL.
- All managed writers upgraded together; no concurrent direct filesystem edits.
- One Gateway process for SQLite, enforced by a process-lifetime file lock.
- Enabled static scanning and a working configured security-scanning model.
  Unavailable or incomplete scans never allow automatic publication.

Grant only the intended owners, trigger agents, operations, and existing skill
names in operator-controlled `config.yaml`, then restart the Gateway:

```yaml
plugins:
  - name: skill-evolution
    use: your_package:install
    host_access:
      evidence:
        owners: ["exact-user-id"]
      skill_mutations:
        owners: ["exact-user-id"]
        operations: [stage, check, commit, revert]
        trigger_agents: [lead_agent]
        target_skills: [your-existing-custom-skill]
        topology: single_host_local
```

This is an example grant, not a bundled plugin. Owner lists are exact and
mutation owners must also have evidence access. Trigger agents are canonical
`AgentConfig.name` values, not display names. Both plugin name and installation
entry point must be unique and stable; changing either changes its durable
identity. Grants bind to host-recorded contribution sources, never plugin-supplied
IDs. They take effect at restart, not live config reload.

These controls prevent mistakes through the supported API. Trusted Python
extensions still have Gateway process privileges and legacy database access;
this is not an untrusted-code sandbox or proof of learning quality.
Ordinary host logs omit candidate contents and raw model errors. Security scans
still send candidate text to the configured model, and operator-enabled tracing
may retain its prompts; apply your provider and tracing data-retention policies.

## Integrate a plugin

Acquire the two optional dependencies in the extension service's `start(deps)`.
All methods are asynchronous; DTOs come from `deerflow_extension_api`.

1. Discover changed runs and obtain a completed-run snapshot. Terminal status
   alone does not mean complete evidence: inspect `seal_state`, coverage limits,
   origin, and canonical agent identity. Pages stay within the snapshot's fixed
   upper sequence; deletion/retention invalidates old references.
2. `read_skill(source_ref=..., name=...)` obtains the opaque target and revision.
3. `stage(source_refs=..., target_ref=..., expected_revision=..., content=...,
   idempotency_key=...)` persists an immutable candidate.
4. Inspect `read_proposal_bundle(proposal_id=...)` to evaluate the exact full
   baseline and candidate. These detached bytes are never activated as skills.
5. `check(proposal_id=...)` runs fail-closed host checks; require `allow`.
6. `commit(proposal_id=..., idempotency_key=..., assessment_ref=...)` returns a
   durable operation. An optional assessment reference records the plugin's
   evaluation; the host neither fetches its URL nor endorses its conclusion.
7. After response loss, use `find_operation(idempotency_key=..., method="commit")`
   or retry with the **same** arguments and key. A different key is not a safe
   way to retry a logically identical request.

P0 updates only existing, enabled, user-custom `SKILL.md` body and description.
Every other parsed frontmatter value, including unknown fields, stays unchanged.
It cannot create, rename, delete, toggle, or modify support files. Symlinks and
special files anywhere in the automatic-update package are unsupported.

Revisions include incarnation, mutation sequence, and whole-package digest.
Manual edits, support-file edits, delete/recreate, and enable toggles invalidate
stale proposals, even if content later returns to its original bytes. Unrelated
skills do not share a compare-and-swap revision.

## Limits and retention

The service advertises limits through `.capabilities`:

| Resource | P0 limit |
| --- | --- |
| Main file | 128 KiB |
| Complete package | 256 files / 16 MiB |
| Evidence sources | 20, all for the same owner |
| Pending proposals | 20 per owner/plugin |
| Model scan | 32 text files / 1 MiB total / 128 KiB each / 120 seconds |
| Live scans | 4 globally; 2 per owner/plugin |
| Scan attempts | 20 per owner/plugin per hour, including failed checks and reverts |
| Proposal / check lifetime | 24 hours / 15 minutes |
| Rollback snapshot lifetime | 30 days |

Oversized bundles fail as a whole. A scan never approves only the first part of
a package. Model-based checks can incur model cost, even though the host does
not generate evolved skills. Metadata and idempotency records survive blob
expiry; expired rollback bytes are no longer available. Recovery references for
unresolved operations are not garbage-collected.
The legacy JSONL history receives only an idempotent, compact metadata mirror,
not retained skill bodies. Repair replays at most the latest 100 applied
operations per owner; files above 8 MiB, lines above 64 KiB, or malformed history
are left untouched. The operation database remains authoritative even if the
display mirror is unavailable.

A cancelled scan or expired scan deadline propagates to the caller and releases
its proposal/scan leases without caching an `unavailable` verdict for 15 minutes.
The attempt still counts against scan-cost quotas. Retrying `check()` starts a
fresh scan; cancelling one waiter alone leaves a shared in-flight scan running
for its other waiters. Completed unavailable/rejected verdicts retain the normal
cache policy.

## Publication, recovery, and rollback

Publication and derived-view readiness are separate. `APPLIED` means canonical
bytes are committed; `views=ERROR` does not mean they were rolled back. Keep the
operation ID and inspect its current state rather than blindly resubmitting.

Before touching canonical bytes, the host durably records `PREPARED`, before/after
snapshots, and reserved versions. It then atomically replaces and fsyncs the main
file. Recovery compares the exact package with those snapshots:

- Before snapshot: `ABORTED`; an unapplied candidate is never replayed.
- After snapshot: finalize `APPLIED` with the reserved version exactly once.
- Neither: `NEEDS_REPAIR`; do not overwrite possible human work.

Affected owner reads remain gated while publication is unresolved. Other owners
remain usable. Recovery belongs to DeerFlow, so disabling or uninstalling the
originating plugin does not disable coordination or recovery.

Administrators using session authentication can discover unresolved publication
or view operations through paginated `GET /api/skill-mutations/operations`
(`limit` up to 100, `after_id` from `next_cursor`). Operation pagination ends
with `has_more: false` and `next_cursor: null`, including an empty page after a
supplied cursor. They can query
`GET /api/skill-mutations/operations/{operation_id}`, reconcile through
`POST /api/skill-mutations/operations/{operation_id}/recover`, or reconcile an
owner's interrupted managed writes through
`POST /api/skill-mutations/owners/{owner_id}/recover`. Ordinary users and personal
access tokens cannot use these endpoints. If reconciliation cannot clear the
owner's readiness barrier, either recovery endpoint returns HTTP 409 with
`detail: "NEEDS_REPAIR"`; query the operation to inspect its durable state and
retry after repairing the underlying storage problem. A successful response
still requires inspecting `views`, since a projection rebuild can record
`views=ERROR` independently of publication. There is no force-overwrite endpoint.

`revert(operation_id=..., expected_current_revision=..., idempotency_key=...)`
creates a new forward revision only if that operation is still the asset's
current head. It rescans the original package under current policy. A later
manual edit or toggle causes a conflict, not a destructive rollback. Revert and
operation queries can survive source-run deletion; a new commit cannot.

Deleting a conversation does not erase information already distilled into a
skill. Skill removal and deletion of derived information are separate operations;
P0 does not implement automatic derived-content forgetting.

Local measurements on macOS arm64 (five captures, warm local disk): canonical
capture plus digest took a median 4.43 ms for 4 files / 3,120 bytes and 94.03 ms
for 256 files / 16,711,473 bytes. These are package-processing measurements, not
model latency or a deployment throughput guarantee. Reproduce with
`uv run pytest tests/test_skill_mutation_package_cost.py -q -s` from `backend/`.

Live PostgreSQL validation on 2026-09-23 used PostgreSQL 17.11 (aarch64,
`READ COMMITTED`), one pytest host process and two concurrent actors sharing a
disposable database schema: a publication-fence worker thread holding the source
run's `SELECT ... FOR SHARE` lock, and an async `RunRepository.delete()` worker.
The opt-in regression passed six times (five repetitions plus the related suite);
deletion waited for the share lock, then removed both the run and its completed
snapshot. The related mutation/evidence/host suite passed 209 tests. See the
[recorded validation](https://github.com/bytedance/deer-flow/pull/5645#issuecomment-5791306188)
for the command, environment and cleanup.

This verifies the source-fence/deletion interleaving, not a multi-process
PostgreSQL soak. Idempotency, recovery, scan-budget and lease behavior were
covered by deterministic suites, not by concurrent PostgreSQL Gateway workers.
`tests/test_skill_mutation_postgres.py` remains opt-in via
`DEERFLOW_TEST_POSTGRES_URL` and creates/removes its own uniquely named schema.
Validate the intended same-host worker deployment before enabling it; SQLite
results alone do not establish PostgreSQL lock behavior.

## Upgrade and operational rollback

Back up the application database and user skill directories together. Stop all
writers, upgrade all Gateway/embedded writer processes and migrate through
`0038_skill_mutations`, then restart before enabling mutation grants. Do not mix
old and new writers on enrolled assets.

Standalone SDK processes without a Gateway mutation runtime check persisted
owner/asset enrollment on every managed storage access. Enrolled owners are
rejected with `MUTATION_RUNTIME_REQUIRED`; use the Gateway for their skill reads
and writes. Global enable-state writes are also rejected while any owner is
enrolled, because they affect same-named custom skills. Removing the plugin
does not remove this barrier. Unavailable enrollment checks fail closed with
`UNAVAILABLE`; missing/legacy databases and unenrolled owners retain ordinary
SDK access. Processes sharing a skill home must use the same application DB.

To stop automation, disable the plugin or remove mutation grants and restart;
keep the upgraded host running so it can reconcile outstanding operations.
Before downgrading host code, quiesce writers, inspect unresolved operations, and
resolve readiness barriers. Do not downgrade while a `PREPARED` or
`NEEDS_REPAIR` record exists. Restore database and files as a coordinated backup
only under an explicit operator recovery procedure.

This host slice follows up the
[Skill Self-Evolution RFC](https://github.com/bytedance/deer-flow/issues/1865)
and the bilingual
[Plugin Host APIs RFC](https://github.com/bytedance/deer-flow/issues/5539).
Neither RFC implies that this PR ships a learning plugin.
