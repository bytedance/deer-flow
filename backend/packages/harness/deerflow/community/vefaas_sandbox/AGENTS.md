# veFaaS cloud sandbox provider (`deerflow/community/vefaas_sandbox/`)

Provisions managed BytePlus Function Service (veFaaS) Cloud Sandbox instances
over OpenAPI v4 (`Version=2024-06-06`) and reuses `AioSandbox` for the data
plane. General sandbox rules are in [sandbox guide](../../sandbox/AGENTS.md);
operator setup is in [README.md](README.md).

## Verify

```bash
cd backend
uv run pytest tests/test_vefaas_sandbox_provider.py tests/blocking_io/test_vefaas_sandbox.py -q
```

## Rules

- **Sign OpenAPI v4 with raw `sk.encode("utf-8")`.** BytePlus/Volcengine SigV4
  does not prepend `"AWS4"` or `"V4"` to the secret key before deriving
  `k_date`; `tests/test_vefaas_sandbox_provider.py` cross-checks parity with
  `volcenginesdkcore.signv4.SignerV4`.
- **Keep `get()` and `get_scoped()` strictly in-memory.** Never touch the
  ownership store or HTTP client on the event loop; `acquire_async()` runs its
  blocking work on the serializer's executor.
- **Confirm absence via `DescribeSandbox` before clearing quarantine.** An
  accepted `KillSandbox` or a failed probe never proves absence.
- **Fence output mirrors from teardown.** Keep clients and lease renewal active
  until release finishes the copy. Shutdown remains retryable during the mirror.
- **Route credentials through `provider_credentials`.** Use `resolve_api_key`,
  `redact_secret`, and `reject_url_userinfo` rather than restating them.
- **Scope TOS mounts by `derive_sandbox_scope_token`.** Never pass raw
  `user_id` or `thread_id` segments into `InstanceTosMountConfig.BucketPath`.
