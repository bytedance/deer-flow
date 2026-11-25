# BytePlus veFaaS Cloud Sandbox Provider (`deerflow/community/vefaas_sandbox/`)

Runs each DeerFlow thread sandbox on **BytePlus Function Service (veFaaS) Cloud Sandbox** using the All-in-One Sandbox (`all-in-one-sandbox`) image.

- **Control plane**: BytePlus veFaaS OpenAPI (`Version=2024-06-06`, SigV4 HMAC-SHA256) over `httpx` — no extra cloud SDK dependency required.
- **Data plane**: Reuses DeerFlow's `AioSandbox` HTTP client via the Sandbox App's unified access domain (`X-Faas-Instance-Name: <SandboxId>`) or a `{sandbox_id}` URL template.
- **Per-agent skills isolation**: Advertises `supports_agent_skill_isolation = True` and uploads bounded `tar.gz` skill projections into the remote sandbox.
- **Persistent storage**: Supports optional scoped `InstanceTosMountConfig` mounts (bucket prefix derived from `derive_sandbox_scope_token(user_id, thread_id)`) or automatic output mirroring on release.
- **Snapshots, pause/resume & image precache** (opt-in): Supports booting from a base `snapshot_id`, pausing idle sandboxes (`pause_on_idle` / `auto_pause`) with automatic `ResumeSandbox` discovery, creating/restoring thread-scoped snapshots on idle (`snapshot_on_idle`) with retention pruning, and asynchronous image precaching (`precache_images` / `precache_on_startup`).
- **Speculative prewarm**: Supports `sandbox.prewarm: true` (and `prewarm_max_concurrent`) to overlap veFaaS sandbox creation and readiness polling with the first model turn on shared-view runs.

If shutdown overlaps an output mirror, it reports incomplete cleanup and keeps
the sandbox available for the copy. Retry shutdown after release finishes.

## Configuration

```yaml
sandbox:
  use: deerflow.community.vefaas_sandbox:VeFaaSSandboxProvider
  vefaas:
    region: ap-southeast-1
    endpoint: https://vefaas.ap-southeast-1.byteplusapi.com
    function_id: $BYTEPLUS_VEFAAS_SANDBOX_APP_ID
    sandbox_base_url: $BYTEPLUS_VEFAAS_SANDBOX_BASE_URL
    access_key_env: BYTEPLUS_ACCESS_KEY_ID
    secret_key_env: BYTEPLUS_SECRET_ACCESS_KEY
    cpu_milli: 1000
    memory_mb: 2048
    timeout_minutes: 60
    # Optional fast-resume, snapshot & image precache settings (all disabled by default)
    # snapshot_id: snap-base-123
    # pause_on_idle: false
    # auto_pause: false
    # snapshot_on_idle: false
    # snapshot_type: disk              # disk | full
    # snapshot_retention_days: 7       # 1..365
    # max_snapshots_per_sandbox: 3     # 1..100
    # precache_images:
    #   - cr-ap-southeast-1.cr.bytepluses.com/namespace/all-in-one-sandbox:latest
    # precache_on_startup: false
    tos_mount:
      enabled: false
      bucket: $BYTEPLUS_TOS_BUCKET
      prefix: deerflow-user-data
  replicas: 3
  idle_timeout: 600
  ownership:
    type: redis   # required for multi-worker gateways
```

## Snapshot Retention & Cleanup

- When `snapshot_on_idle: true` is enabled, idle snapshots retain the thread's workspace filesystem. Restoring from a snapshot preserves the snapshot's workspace/outputs while still refreshing `/mnt/skills` and syncing host `uploads/` when `/tmp/.deerflow-vefaas-initialized` is already present.
- Set `snapshot_retention_days` (e.g. `7`) alongside `max_snapshots_per_sandbox` (default `3`) in multi-tenant deployments so veFaaS automatically expires snapshots for inactive threads; when `snapshot_retention_days` is omitted, veFaaS applies the platform default retention policy.
- DeerFlow's `SandboxProvider` interface does not currently expose a thread-deletion hook. To delete a thread's snapshots on demand (for example, on user/thread erasure), derive `sandbox_id = derive_sandbox_scope_token(user_id=..., thread_id=...)` and call `provider.delete_snapshot(snap.id)` for each record returned by `provider.list_snapshots(sandbox_id)`.

## Verification

```bash
cd backend
uv run pytest tests/test_vefaas_sandbox_provider.py -q
uv run pytest tests/blocking_io/test_vefaas_sandbox.py -q
```
