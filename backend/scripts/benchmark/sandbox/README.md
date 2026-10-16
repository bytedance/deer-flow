# Sandbox benchmarks

Run from `backend/` with a readable, isolated DeerFlow config and runtime home.
These commands create real sandbox resources; the ordinary unit suite is offline.
Pin the sandbox image and record the Git revision, Docker/VM capacity and config.
Use a disposable home and never point a benchmark at a production provider.

```sh
DEER_FLOW_CONFIG_PATH=/absolute/path/benchmark.yaml \
DEER_FLOW_HOME=/absolute/path/disposable-home \
uv run python scripts/benchmark/sandbox/bench_provider.py \
  --provider aio-docker --image <pinned-image> \
  --scenario cold_unique_thread --no-warmpool --iterations 10 \
  --output cold.jsonl

uv run python scripts/benchmark/sandbox/bench_provider.py \
  --provider aio-docker --image <same-pinned-image> \
  --scenario replica_pressure --users 4 --concurrency 4 --iterations 8 \
  --output pressure.jsonl

uv run python scripts/benchmark/sandbox/summarize.py cold.jsonl pressure.jsonl
```

Each invocation gets an independent run/thread namespace and AIO container prefix.
`--run-id` makes that namespace explicit. AIO cleanup uses the actual acquired ID
and the provider's destruction path, checking that destruction completed. Fault
injection stops that same resource while retaining the stale provider entry to
exercise recovery. Failures in acquisition, command execution, cleanup, or warm-up
make the command fail; inspect row counts and semantic results as well as timing.

`replica_pressure` holds simultaneous active clients behind barriers before running
commands. `barrier_wait_ms` is test synchronization overhead, so its `total_ms` is
not a user-facing latency measurement. The provider's `replicas` is a soft cap;
protecting active work can exceed it. `--users` distributes independent scopes
across synthetic users, not real accounts.

Warm-up resources are destroyed before timed cases. A fresh-thread cold run does
not measure image download or a cold Docker daemon. `acquire_ms`, `run_ms`,
`release_ms` and `cleanup_ms` separate those costs; no-warm-pool `total_ms` includes
explicit destruction. `warm_hit` comes from the actual reclaim path. Keep different
images, pool settings, replica limits, user counts and concurrency levels separate;
the summary's default grouping does so. Percentiles use inclusive interpolation.

## Resource samples

Run the sampler beside an explicit benchmark run ID:

```sh
uv run python -m scripts.benchmark.sandbox.resources \
  --prefix deerflow-bench-my-run- --output resources.jsonl --duration 60
# In another terminal, use --run-id my-run in the provider benchmark.
```

Only containers with the exact name prefix are sampled. This sampler never
creates or destroys resources. Failed or incomplete readings stay unknown, not
zero. Peaks are observed sample peaks; Docker memory and CPU omit host/VM overhead.
Join these records with the provider's active/warm snapshots before interpreting
resource use. Record host/daemon capacity separately and do not compare stripped
code-only images with a browser-enabled image as equivalent functionality.

This provider microbenchmark does not measure model latency, speculative startup
prediction, complete Agent runs, or first-tool overlap. Those need a separate
production-runtime experiment with controlled model behavior.
