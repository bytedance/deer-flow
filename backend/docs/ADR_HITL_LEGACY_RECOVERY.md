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
