# Sandbox Memory Profiling

This guide records a repeatable baseline before changing the sandbox runtime.
Issue #3213 reports per-sandbox memory near 1 GiB in Kubernetes. Before adding
or recommending a new provider, capture the current AIO sandbox baseline and
compare candidates with the same DeerFlow workload.

## What to Measure

Measure at least these samples:

1. Empty sandbox after it becomes ready.
2. After a simple bash command.
3. After a Python task that imports common packages.
4. After a Node task when Node-based workloads are expected.
5. After generating files under `/mnt/user-data/outputs`.
6. After release and warm reuse.
7. At the target concurrency level, for example 10, 50, or 100 sandboxes.

`kubectl top` reports Kubernetes/container working set memory. Treat it as a
capacity signal, not exclusive RSS/PSS. Pod-level memory includes every
container in the Pod and may include cache charged to the cgroup. If a result
looks surprising, inspect the sandbox processes and cgroup metrics on the node
before drawing conclusions.

## Capture a Snapshot

Run this from the repository root:

```bash
python scripts/sandbox_memory_profile.py \
  --namespace deer-flow \
  --selector app=deer-flow-sandbox \
  --sample empty \
  --include-processes \
  --format markdown
```

Use a descriptive `--sample` value for each phase:

```bash
python scripts/sandbox_memory_profile.py --sample after-bash --format json
python scripts/sandbox_memory_profile.py --sample after-python --format json
python scripts/sandbox_memory_profile.py --sample after-artifact --format json
```

`--include-processes` runs `kubectl exec ... ps` in each sandbox Pod and adds
the highest-RSS processes to the report. This helps distinguish Pod-level cgroup
memory from process RSS. The two numbers will not match exactly because cgroup
memory can include cache and other kernel-accounted memory.

Save the raw JSON when comparing backends so totals, pod names, images,
requests, limits, and timestamps can be audited later.

## Candidate Runtime Matrix

For AIO, CubeSandbox, OpenSandbox, gVisor, Kata, or another candidate, compare
the same workload and record:

| Area | Required Evidence |
| --- | --- |
| Capacity | Pod or instance count, total memory, average memory, max memory |
| Startup | Ready latency at 1, 10, 50, and 100 concurrent sandboxes |
| Commands | Bash output, timeout behavior, failure shape |
| Files | `read_file`, `write_file`, binary `update_file`, `list_dir`, `glob`, `grep` |
| Uploads | Files uploaded by the gateway are visible inside the sandbox |
| Artifacts | Files written to `/mnt/user-data/outputs` are readable by the backend artifact API |
| Paths | `/mnt/user-data/workspace`, `/mnt/user-data/uploads`, `/mnt/user-data/outputs`, `/mnt/acp-workspace`, and skills paths keep their expected semantics |
| Isolation | Different users and threads cannot read each other's data |
| Cleanup | Release, idle timeout, process restart, and orphan cleanup free resources |
| Operations | Deployment prerequisites, privileged components, networking, storage, and upgrade path |

## PR Guidance

Do not claim that a new provider fixes high-concurrency memory usage until the
same DeerFlow workload has been measured on both the current AIO sandbox and the
candidate backend.

For an experimental provider PR, prefer `Related to #3213` unless the PR also
includes reproducible DeerFlow workload data that demonstrates the target memory
reduction and preserves uploads, outputs, artifacts, and isolation behavior.
