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

`summarize.py` summarizes only `bench_provider.py` results. It reports and ignores
metadata and typed prewarm/resource records before aggregation and exit-status
checks. Inputs containing no provider results fail with a format diagnostic;
failed provider rows still make the summary exit nonzero.

Each invocation gets an independent run/thread namespace and AIO container prefix.
`--run-id` makes that namespace explicit. AIO cleanup uses the actual acquired ID
and the provider's destruction path, checking that destruction completed. Fault
injection stops that same resource while retaining the stale provider entry to
exercise recovery. Failures in acquisition, command execution, cleanup, or warm-up
make the command fail; inspect row counts and semantic results as well as timing.

`replica_pressure` holds simultaneous active clients behind barriers before running
commands. `barrier_wait_ms` is test synchronization overhead, so its `total_ms` is
not a user-facing latency measurement. Turn timing starts inside the worker after
it acquires its scope lock: executor-queue and scope-lock waits are excluded.
Pressure batches are submitted sequentially; later batches do not represent
requests already waiting in an admission queue. The provider's `replicas` is a soft cap;
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

## First-tool overlap and unused prewarming

The prewarm driver uses a different JSONL format; do not pass its output to
`summarize.py`. Its exit status checks case outcomes and batch cleanup. Inspect
`prewarm_case` and `batch_cleanup` records for their separate `success` fields;
the `configuration` record has no outcome and must not count as a failed case.

The provider microbenchmark does not measure first-tool overlap. For that, use
the compiled-agent experiment with the same isolated config/home and pinned image:

```sh
uv run python -m scripts.benchmark.sandbox.bench_prewarm \
  --image <pinned-image> --cases tool plain fenced_no_tool model_error cancel \
  --model-delays 0 1 3 --iterations 5 --output prewarm.jsonl

uv run python -m scripts.benchmark.sandbox.bench_prewarm \
  --image <same-pinned-image> --cases tool fenced_no_tool cancel \
  --model-delays 3 --iterations 2 --users 4 --concurrency 4 \
  --replicas 2 --prewarm-max-concurrent 1 --output prewarm-pressure.jsonl
```

This uses a scripted model with production thread/sandbox middleware, the bash
tool, authorization, and execution-lease cleanup. Containers and commands are
real; model delays and users are synthetic. No paid model is called, and this is
not a standalone SDK prewarm example: the driver explicitly registers its
unconditional execution cleanup, as the Gateway/embedded worker and native
subagent executor do. Direct SDK graphs retain lazy acquisition. This is
not a Gateway HTTP/SSE or live-model latency measurement. Each A/B pair has the
same prompt and predetermined tool intent, randomized variant order, fresh thread
IDs, and exact-resource destruction between batches. Output paths must be new.

`first_tool_wait_ms` spans the sandbox initialization entry until it is usable;
the bash tool's preceding authorization scope and graph dispatch are outside
that interval. Derive response-to-ready wait from `events_ms.tool_ready -
events_ms.model_first_response` to include them. `elapsed_ms` also includes graph
construction and terminal cleanup. A reused prewarm is not necessarily model
overlap: compare acquire/model event timestamps, especially in the zero-delay
control, and do not attribute startup jitter to prewarming.
`unused_active_ms` ends when an unused acquisition is parked:
it excludes subsequent warm-pool residency. Lease cleanup does not imply physical
container destruction; ordinary idle eviction still applies. `replicas` and the
speculative budget do not enforce deployment-wide admission or user fairness.

Join per-case monotonic windows and lifecycle snapshots with the companion
`.resources.jsonl`; a whole-file peak mixes enabled/disabled cases and teardown.
Keep those phases separate when comparing memory or CPU. Record dirty-tree/driver
hashes and inspect semantic success, cleanup records, and process exit status.
