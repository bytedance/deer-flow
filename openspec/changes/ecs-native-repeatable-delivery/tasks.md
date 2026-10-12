# Tasks

- [x] 1. Separate accepted runtime snapshot (1558a120) and historical evidence snapshot (b1ee35c7); preserve 67 original input hashes.
- [x] 2. Implement immutable build/export/transfer and guarded same-schema rollout with per-step receipts and no automatic resume.
- [x] 3. Document private inputs, recovery, scope boundaries and historical/current entry distinctions.
- [x] 4. Complete Ruff/format, Python compilation, shell syntax, OpenSpec strict validation and 67 historical hashes; preserve the delivery implementation in a separate local commit. Its commit identity is recorded in the private resume checkpoint.
- [ ] 5. After user starts Shanghai ECS, recover existing mounts/services and run five guard tests plus one Jenkins delivery main; then one chosen real workflow smoke.

Implementation is prepared; cloud validation remains pending. No remote Git publication or cloud mutation in this phase.

2026-10-12 cloud checkpoint: guard #3 SUCCESS (5 cases, 0.018s); original #1/#2 workspace/@tmp failures retained. Recovery #2 SUCCESS after correcting read-only runs.run_id audit; #1 retained. NAS binds, original e84 container IDs, private fingerprints, native0035/executor e0001 and three-table history hashes preserved; strict TLS, worker500m/1GiB and drain/unreleased0 verified, no model calls. Prepared-checkout entry passes actual Jenkins Groovy validation. Task5 still awaits new build/transfer/deploy/readiness and one real workflow.
