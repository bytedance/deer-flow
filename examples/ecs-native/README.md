# Native operator configuration

Use the same `nodes` definition for the B pool and native central host. Merge B
profiles into that shared operator definition; do not create a second capacity
ledger. The worker has no ledger database URL and makes outbound HTTP requests.
The native Gateway still needs its normal shared PostgreSQL/Redis/JWT/NAS config.

Worker native sandbox configuration requires `AioSandboxProvider`, image
`enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:1.11.0`,
`replicas: 1`, `hard_capacity: true`, and Redis ownership. Set
`DEER_FLOW_SANDBOX_CPUS=1` and `DEER_FLOW_SANDBOX_MEMORY=1g`. Supervise the Linux
Gateway under actual 500m CPU/1 GiB cgroup limits. The native role and ordinary B
worker use separate node locks. See the package README for evidence and pending
configured capability/deployment boundaries.

`native-shell.yaml` is a runnable shell-main native config for both roles. Set
`DEER_FLOW_CONFIG_PATH` to it, `ECS_NATIVE_CONFIG` to the matching JSON,
`DEER_FLOW_HOME` to the shared native NAS root, and database/Redis/model/auth
environment variables. Use distinct container prefixes for separate node roles.
Set the same `AUTH_JWT_SECRET` and `DEER_FLOW_INTERNAL_AUTH_TOKEN` on both peers.
The JSON ledger URL uses SQLAlchemy's `postgresql+psycopg://` driver; the native
database URL uses the normal native `postgresql://` form. This example has only
the native profile. For C→B→C, add an operator B profile to this same node definition
and configure the ordinary MCP server/daemon against the same SQL ledger. Enable
native MCP tasks and bind the frozen `user_auth` credential to the actual native
owner; do not use a model-supplied owner ID. The combined executable example is
`backend/tests/test_ecs_executor_bc_main.py`: it builds the shared pool and validates
full C finalization, B attempt 1, exactly two native runs, same-goal budgets and
native artifact delivery. These shell examples do not enable browser/memory;
configured browser capability and cloud deployment acceptance remain separate gates.

For the configured native Scheduler slice, retain the same shared infrastructure
and add these settings to both normal native Gateway configurations:

```yaml
scheduler:
  enabled: true
  tool_enabled: true
  multi_instance: true
```

The central role runs native background dispatch. The execution-only worker keeps
native foreground schedule tools and completion hooks while its trusted host
disables background claims. Manual triggers there persist in the same queue for
central dispatch. Browser/UI ingress stays on the control Gateway. See
[Native Scheduler roles](../../backend/packages/ecs-executor/README.md#native-scheduler-roles)
for readiness semantics and the exact single-case acceptance command; its fixture
reuses the same owned PostgreSQL/Redis/AIO infrastructure and automatically
launches a genuine scheduled occurrence before C→ordinary MCP B→same-goal C.

For native memory, merge the `memory` section from `native-memory.yaml` into each
role's normal Gateway config. Keep `DEER_FLOW_HOME` on the same canonical shared
NAS root. Leave `memory.backend_config.storage_path` omitted so normal native
per-user paths and owner resolution remain active. Set
`DEER_FLOW_MEMORY_INDEX_PATH` to an absolute local directory unique to each
Gateway instance (for example `/var/cache/deerflow/central-memory` on central
and `/var/cache/deerflow/worker-memory` on the worker). This derived SQLite FTS
index, including its WAL/SHM files, must not be on NAS; it can be rebuilt from
shared Markdown facts and their revision manifest. Replicas on the same host
need different local directories too.

`native-memory.yaml` is a partial overlay, not a complete startup config. From
`backend/`, create a separate merged config with only its `memory` section replaced;
this preserves the base model/database/auth settings and environment references.
The exclusive file creation refuses to overwrite an existing merged config:

```bash
.venv/bin/python - ../examples/ecs-native/native-shell.yaml \
  ../examples/ecs-native/native-memory.yaml /private/operator/native-memory-config.yaml <<'PY'
import sys
from pathlib import Path
import yaml

base_path, overlay_path, output_path = map(Path, sys.argv[1:])
base = yaml.safe_load(base_path.read_text())
overlay = yaml.safe_load(overlay_path.read_text())
assert isinstance(base, dict) and isinstance(overlay, dict) and set(overlay) == {"memory"}
base["memory"] = overlay["memory"]
with output_path.open("x", encoding="utf-8") as output:
    yaml.safe_dump(base, output)
PY
export DEER_FLOW_CONFIG_PATH=/private/operator/native-memory-config.yaml
export DEER_FLOW_MEMORY_INDEX_PATH=/var/cache/deerflow/central-memory
```

Use an existing protected operator directory for the output, and substitute your
normal role config as the base when it contains deployment-specific model/auth
settings. For the worker, generate its own merged config and choose its own local
index directory. Keep the existing `ECS_NATIVE_CONFIG` role selector and shared
`DEER_FLOW_HOME`, PostgreSQL/Redis/auth/model environment settings. Start the normal
native Gateway using `DEER_FLOW_CONFIG_PATH` pointing to the merged config; do not
point it at the partial overlay.

The overlay uses native DeerMem tool mode: the model calls `memory_search`,
`memory_get`, and fact CRUD explicitly; DeerMem does not run passive extraction
in this mode. The fixture's opt-in memory main preserves the shell, ordinary BC,
and scheduled defaults and uses one actual model run to retrieve an API-seeded
UUID fact absent from its prompt, add another fact on the remote worker, and
deliver the retrieved fact through native files. It checks both peer APIs,
server-owned Run identity, another owner's isolation, and separate local indexes.
Run just this case from `backend/` with existing Docker images/environment:

```bash
ECS_NATIVE_LIVE=1 ECS_NATIVE_MODEL_CONFIG=/private/config.yaml \
  ECS_NATIVE_MODEL_ENV=/private/.env PYTHONPATH=.:packages/ecs-executor \
  .venv/bin/python -m pytest \
  tests/test_ecs_executor_c_live.py::test_native_remote_memory_shared_facts_and_owner_isolation -q -s
```

This local two-process acceptance uses a shared directory as the canonical NAS
stand-in. Actual cloud NAS locking/durability and Gateway cgroups still require
cloud deployment acceptance. The memory overlay does not enable browser tools.

For native browser control, append the tools in `native-browser.yaml` to the
normal Gateway tools list and add `browser_control.provider` with
`ecs_executor.browser:build_browser_control_provider` to both role JSON files.
The overlay preserves production SSRF/egress guards and never enables CDP.
The fixed serial worker opens an outbound TLS WebSocket to central; the UI stays
on central and reaches the same native session as model tools. The new provider
is a trusted optional Gateway hook, not a public extension. See the package's
[Native browser affinity/control](../../backend/packages/ecs-executor/README.md#native-browser-affinitycontrol)
for startup, authentication, physical-capacity, reverse-proxy, and acceptance
boundaries. The central and worker JSON examples remain browser-disabled by
default; explicitly merge the provider section only when browser tools are enabled.
