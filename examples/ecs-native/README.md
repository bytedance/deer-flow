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
native artifact delivery. These shell examples do not enable browser/memory; full
configured capabilities and cloud deployment acceptance remain separate gates.
