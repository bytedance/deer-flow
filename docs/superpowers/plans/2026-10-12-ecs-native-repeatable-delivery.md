# Native ECS repeatable delivery plan

The accepted B/C/BC application behavior is frozen. This plan addresses the release path and auditability.

1. Inventory the dirty feature worktree. Commit runtime/build/config/docs/tests first; retain historical scripts without changing their contents or original evidence hashes.
2. Add one versioned Jenkins entry that accepts a release manifest, verifies a clean source commit and digest, builds the backend native role from that source, binds the independently accepted frontend image in the private target plan, records the backend image ID and export digests, then transfers only the locked backend archive. Deployment uses the existing private operator controls and keeps admission drained.
3. Document the private manifest inputs, preconditions, stage receipts, recovery order and failure behavior. No keys or private environment are committed.
4. Run syntax, formatting, OpenSpec validation and static manifest/entry checks without local Docker; execute the five guard tests on Jenkins. Once Shanghai ECS is powered on, verify only the release path and one business smoke; retain prior B/C/BC acceptance evidence.
