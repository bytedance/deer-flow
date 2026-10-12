# Tasks

- [x] 1. Separate accepted runtime snapshot (1558a120) and historical evidence snapshot (b1ee35c7); preserve 67 original input hashes.
- [x] 2. Implement immutable build/export/transfer and guarded same-schema rollout with per-step receipts and no automatic resume.
- [x] 3. Document private inputs, recovery, scope boundaries and historical/current entry distinctions.
- [x] 4. Complete Ruff/format, Python compilation, shell syntax, OpenSpec strict validation and 67 historical hashes; preserve the delivery implementation in a separate local commit. Its commit identity is recorded in the private resume checkpoint.
- [ ] 5. After user starts Shanghai ECS, recover existing mounts/services and run five guard tests plus one Jenkins delivery main; then one chosen real workflow smoke.

Implementation is prepared; cloud delivery validation remains pending. Remote Git publication remains paused.

2026-10-12 cloud checkpoint: guard #3 SUCCESS (5 cases, 0.018s); original #1/#2 workspace/@tmp failures retained. Recovery #2 SUCCESS after correcting read-only runs.run_id audit; #1 retained. NAS binds, original e84 container IDs, private fingerprints, native0035/executor e0001 and three-table history hashes preserved; strict TLS, worker500m/1GiB and drain/unreleased0 verified, no model calls. Prepared-checkout entry passes actual Jenkins Groovy validation. Task5 still awaits new build/transfer/deploy/readiness. One real workflow completed subsequently as recorded below.

2026-10-12 business checkpoint: deerflow-native-business-sales-20261012 #3 SUCCESS, 172.310s; one actual DeepSeek C→B→C sales-CSV workflow, authenticated output200, independently recalculated total340000 cents. Two native Runs success, B attempt1, all three jobs physically completed, automatic delivered notification, goal cleared. Final drain/unreleased0 and original e84 worker healthy500m/1GiB verified. #1/#2 failed before business admission (validation-script import scope / 76-char thread ID exceeding native64); failures retained. No model replay, runtime patch or expanded matrix. Independent receipt ba772155d11c8856223ac816c085323163fab991ce792c07c3135fb2d06c1935. Task5 stays unchecked pending the new delivery main.
