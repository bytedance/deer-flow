# Tasks

- [x] 1. Separate accepted runtime snapshot (1558a120) and historical evidence snapshot (b1ee35c7); preserve 67 original input hashes.
- [x] 2. Implement immutable build/export/transfer and guarded same-schema rollout with per-step receipts and no automatic resume.
- [x] 3. Document private inputs, recovery, scope boundaries and historical/current entry distinctions.
- [x] 4. Complete Ruff/format, Python compilation, shell syntax, OpenSpec strict validation and 67 historical hashes; preserve the delivery implementation in a separate local commit. Its commit identity is recorded in the private resume checkpoint.
- [ ] 5. After user starts Shanghai ECS, recover existing mounts/services and run five guard tests plus one Jenkins delivery main; then one chosen real workflow smoke.

Implementation is prepared; cloud validation remains pending. No remote Git publication or cloud mutation in this phase.
