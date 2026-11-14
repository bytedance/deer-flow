# ADR: reject-only recovery of legacy unaddressable HITL pauses

Date: 2026-11-10. Upstream baseline: c612531213b2505857bf733a6a332fd7653f84b4.
Scope: bytedance/deer-flow #8071, separate from prevention work in #8070.

The Gateway currently validates stored tool IDs before considering all-reject.
A persisted null/duplicate-ID pause therefore cannot be rejected or replaced.

Decision: recognize only otherwise well-formed legacy null/duplicate-ID payloads.
Admit only an explicit, nonempty all-reject response matching that payload's
actions. Carry a server-created, content-free digest identity through the
existing answer/restore lifecycle. Revalidate the same identity at attachment;
keep the existing durable waiting-status and top-level request-ID CAS. Never
pass an unbound None identity for this recovery. Checkpoint-only retry must
target the same digest. Normal valid-pause identity matching is unchanged.

On graph replay, unaddressable calls are removed from all provider-serialized
surfaces, including ordinary calls sharing their IDs. Add a visible rejection
note; no fabricated result for a null ID and no approval of an ambiguous call.
Keep the pre-interrupt guard merged in #8070; do not add a migration, a new endpoint,
an execution bypass, or an automatic retry of tools. No new persistent data.

Verification: red/green legacy null/duplicate recovery, mixed-decision refusal,
stale valid and invalid pause binding, checkpoint-only retry, failed attachment
rollback, memory/SQLite answer CAS, native graph non-execution and provider
payload cleanup, full/delta authenticated Gateway regressions where feasible.
Record missing real-provider, PostgreSQL and full-suite checks explicitly.

Upstream #8073 shares matched durable actions between replay-gate names and
journal adoption. Legacy recovery performs its exact all-reject match in that
action lookup, preserving ordinary history reconciliation and stale-pause checks.

After #8070 merged, retain its whole-response ambiguity guard and last-message
denial API. Use its single `_strip_calls` path for prevention, denial and legacy
replay, extending cleanup to null-ID siblings, matching invalid calls and
unidentifiable legacy function_call metadata. Keep legacy identity admission
exact and require integer version 1 excluding booleans.

## Approval v2 compatibility (2026-11-14)

Main at 4f3a8b7 replaces the version-1 after-model gate with the version-2
operation approval middleware. Do not restore version-1 approval generation or
change version-2 Ask/Auto/Full decisions to resolve this integration conflict.

For a validated, reject-only unaddressable version-1 pause, retain the original
`HitlApprovalMiddleware.after_model` graph node name through a small recovery-only
compatibility middleware. Assemble it only from worker-recovered durable actions,
never from caller context. It performs one rejection cleanup, consumes no new
authorization, creates no new interrupt, and becomes inert after that replay.
The normal version-2 middleware retains ownership of subsequent operations.

Only one original legacy interrupt can enter digest-bound recovery. Multiple
parallel version-2 interrupts continue through their existing interrupt-ID resume
map; mixed legacy/parallel batches fail closed. Keep the durable answer/restore
identity, single-winner CAS, and exact grouped-response matching.

Verification must seed a version-1 checkpoint with its original node name, then
restore production assembly before recovery. Exercise the real Gateway with
full/delta checkpoints, configuration changes and checkpoint-only retry. Keep
version-2 call-ID, parallel approval and edited-argument tests in the selection.
