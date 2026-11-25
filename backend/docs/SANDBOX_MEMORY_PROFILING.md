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

## AIO idle baseline and the lean profile

Measured on `all-in-one-sandbox:1.11.0` with a local Docker run, no workload,
and `/v1/sandbox` answering 200 in every configuration:

| Configuration | Idle memory |
| --- | --- |
| Image defaults | 725 MiB |
| `DISABLE_JUPYTER=true`, `DISABLE_CODE_SERVER=true` | 281 MiB |
| The two above plus `DISABLE_BROWSER`, `DISABLE_MCP_BROWSER`, `DISABLE_VNC`, `DISABLE_NODEJS_REPL` | 165 MiB |

The image also reads `DISABLE_BROWSER`, `DISABLE_MCP_BROWSER`, `DISABLE_VNC` and
`DISABLE_NODEJS_REPL`. Turning those off removes browser screenshots, the
browser MCP server, the desktop view and Node REPL execution, so decide per
deployment whether the agent stack needs them.

The same image was measured in a temporary Kubernetes 1.31.5 cluster (k3d,
one node) with no workload. Every Pod answered `/v1/sandbox` with 200 after
90 seconds of idle time, and memory came from the Pod's cgroup
`memory.current`:

| Configuration | Kubernetes idle memory |
| --- | --- |
| Image defaults | 544 MiB |
| `DISABLE_JUPYTER=true`, `DISABLE_CODE_SERVER=true` | 317 MiB |
| The two above plus `DISABLE_BROWSER`, `DISABLE_MCP_BROWSER`, `DISABLE_VNC`, `DISABLE_NODEJS_REPL` | 191 MiB |

Kubernetes adds kubelet and container-runtime overhead and can report different
values from `docker stats`. Compare profiles in the same cluster; the relative
reduction is what decides whether the lean profile fits the deployment.

Deployments set these through `sandbox.environment`, which reaches local Docker
containers and, through the provisioner, Kubernetes sandbox Pods. The Kubernetes
path needs a provisioner that forwards that map: older provisioners ignore it
and start the Pod with image defaults, so upgrade them first. Pods that already
exist keep the environment they were created with until they are recreated. The
provisioner accepts at most 32 operator entries, names matching
`[A-Za-z_][A-Za-z0-9_]*` within 64 characters, and values of up to 1024
characters; the Gateway checks the same limits at startup, so a map it cannot
deliver stops the process with `sandbox.environment` named.

```yaml
sandbox:
  use: deerflow.community.aio_sandbox:AioSandboxProvider
  environment:
    DISABLE_JUPYTER: "true"
    DISABLE_CODE_SERVER: "true"
```

Keep a measured record of any other combination before recommending it. The
numbers above are idle figures; the workload samples in the first section decide
whether a lean profile still serves the tools an agent uses.

## PR Guidance

Do not claim that a new provider fixes high-concurrency memory usage until the
same DeerFlow workload has been measured on both the current AIO sandbox and the
candidate backend.

For an experimental provider PR, prefer `Related to #3213` unless the PR also
includes reproducible DeerFlow workload data that demonstrates the target memory
reduction and preserves uploads, outputs, artifacts, and isolation behavior.
