# Multi-tenant personal assistant with managed and self-service onboarding

## Why
The user requires one release covering operator-created tenants and customer self-registration/team management for personal research, reports and recurring follow-up. Existing user-scoped resources and native signup do not prove tenant isolation across background execution.

## What Changes
- Reuse native accounts/auth/roles, Run/MCP/Scheduler/memory and B/C infrastructure; add workspaces, membership and trusted scope.
- Deliver managed onboarding, verified self-registration, recovery, invitations, team roles and ownership transfer together.
- Isolate resources, retrieval, credentials, memory, execution, browser sessions and notifications; persist revocation and lifecycle operations.
- Add basic quotas, usage, audit, account/workspace closure, migration/recovery and one research-follow-up workflow.

## Scope
Plan-only in this turn. Implementation runs M0 through M11 sequentially on Shanghai Jenkins. No local Docker/pytest, deployment or new publication in this turn. Billing, new enterprise SSO, custom role builders and dedicated tenant deployments are excluded.

## Capabilities
### New Capabilities
- tenant-workspaces: unified membership, onboarding, resource and execution isolation with lifecycle and rollout contracts.

## Impact
Auth and authz, native repositories/migrations, Paths/memory/knowledge/MCP, ECS signed scope, frontend workspace/auth surfaces, and Jenkins schema-aware delivery. This is a cross-cutting schema change, not a plugin-only feature or an already accepted enterprise isolation guarantee.
