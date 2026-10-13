# Make native ECS delivery repeatable

## Why
The native B/C/BC runtime has been accepted on Shanghai ECS, but the accepted source remains an uncommitted worktree and the Jenkins jobs are immutable, release-specific evidence. Re-running those jobs for a new revision would use stale hashes.

## What Changes
- Commit the accepted runtime, configuration, tests, deployment guide and acceptance evidence as reviewable snapshots.
- Keep historical Shanghai scripts and Jenkinsfiles as historical evidence, separate from the supported delivery entry.
- Introduce a versioned, manifest-driven Jenkins build/export/transfer and guarded deployment procedure. A release must bind a Git commit, source archive, image identity, target role and schema before deployment.
- Preserve drain, physical STOP, owner scope, two-database and NAS history; never auto-resume.
- Verify the new delivery path on Jenkins/ECS only after machines are available. The previous accepted application mainlines need no repeat merely for pipeline refactoring.

## Scope
No remote Git publication, cloud mutation, secret copying, new execution architecture or local Docker Desktop work.

## Capabilities
### New Capabilities
- native-release-delivery: immutable source/image lock and fail-closed same-schema operator rollout.

## Impact
Root operator scripts, one dedicated Jenkinsfile, private selector template, five guard cases and delivery documentation. No runtime execution API or database schema changes.
