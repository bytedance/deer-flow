# BytePlus veFaaS Cloud Sandbox Provider (`deerflow/community/vefaas_sandbox/`)

Runs each DeerFlow thread sandbox on **BytePlus Function Service (veFaaS) Cloud Sandbox** using the All-in-One Sandbox (`all-in-one-sandbox`) image.

- **Control plane**: BytePlus veFaaS OpenAPI (`Version=2024-06-06`, SigV4 HMAC-SHA256) over `httpx` — no extra cloud SDK dependency required.
- **Data plane**: Reuses DeerFlow's `AioSandbox` HTTP client via the Sandbox App's unified access domain (`X-Faas-Instance-Name: <SandboxId>`) or a `{sandbox_id}` URL template.
- **Per-agent skills isolation**: Advertises `supports_agent_skill_isolation = True` and uploads bounded `tar.gz` skill projections into the remote sandbox.
- **Persistent storage**: Supports optional scoped `InstanceTosMountConfig` mounts (bucket prefix derived from `derive_sandbox_scope_token(user_id, thread_id)`) or automatic output mirroring on release.

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
    tos_mount:
      enabled: false
      bucket: $BYTEPLUS_TOS_BUCKET
      prefix: deerflow-user-data
  replicas: 3
  idle_timeout: 600
  ownership:
    type: redis   # required for multi-worker gateways
```

## Verification

```bash
cd backend
uv run pytest tests/test_vefaas_sandbox_provider.py -q
uv run pytest tests/blocking_io/test_vefaas_sandbox.py -q
```
