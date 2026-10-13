# Design references and decisions

Canonical Chinese design: `../../../docs/superpowers/specs/2026-10-13-tenant-workspaces-design.md`.
Sequential implementation plan: `../../../docs/superpowers/plans/2026-10-13-tenant-workspaces.md`.
Baseline: 48d5c3de. Scope approved; implementation not started.

Workspace is the tenant, user remains global, membership carries tenant roles. Native permissions intersect resource ACLs and active membership. Platform administrator has no implicit content bypass. Threads remain owner-private; sharing is explicit for project materials and reports. Trusted scope is resolved server-side and persists through native execution, not inferred from the user's current UI workspace.

Reuse native signup and account repository; add verified onboarding and single-use lifecycle tokens. Invitations bind verified email. Shared Redis limits public enrollment. Keep global plugin installation operator-only.

Schema changes require additive migrations, explicit legacy-owner backfill, separate executor migration receipts, NAS mappings and tested restore. Old same-schema release locks reject new schema; no automatic legacy task replay.

Default execution is sequential. UI and managed/self-service flows ship together only after tenant boundary and cloud evidence gates pass.
