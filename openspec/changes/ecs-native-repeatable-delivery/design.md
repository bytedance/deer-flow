# Design

Use a dedicated job and a clean full Git commit. Build only the native backend role; preserve the independently accepted immutable frontend. Export source and image once, record their digests and image schema labels in release.json, and bind each remote receipt to the release and private environment digest.

Private targets contain only operator selectors and fingerprints, not credentials. Verify canonical owned paths, mounted NAS marker, same schema, installed prior images, exact Compose/config generation and strict TLS. The rollout requires drain and settled native/physical accounting. Fence controller ingress and Gateway before stopping the idle worker. Preserve controller PG/Redis/UI/proxy identity, recreate only Gateway/MCP, reload the retained proxy, then start the new worker. Never resume automatically.

Save each step immediately and refuse whole-rollout replay after any partial evidence. Preserve preselection ops snapshots and all failure history. Schema migration, first initialization, UI rollout and point-in-time restore remain separate reviewed operations.

The two Shanghai machines are off. Static checks can run now; five guard tests and an actual release main must run on Jenkins after recovery. Do not infer cloud acceptance from preparation.
