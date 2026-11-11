# BoxLite provider

- `provider.py` owns one private asyncio loop. Fresh and startup-recovered boxes
  must execute, collect output, wait, and stop on that loop, including calls from
  arbitrary synchronous tool workers. Do not use the greenlet sync SDK or
  `asyncio.run()` for recovered handles.
- Startup recovery is get-only: list DeerFlow-prefixed names and look them up
  through the async runtime. Skip missing entries. `SimpleBox(reuse_existing=True)`
  uses `get_or_create` and can create a VM, so it is not a get-only attach API.
- The recovered-box adapter translates argv and environment to native lists,
  forwards `user`, `cwd`, and `timeout_secs`, drains stdout/stderr concurrently,
  and waits for completion before returning the public SDK `ExecResult`.
  Preserve `SimpleBox.exec` semantics for bytes, partial stream failures, and
  failed waits (`exit_code=-1`).
- Keep SDK imports lazy: ordinary harness installs do not include BoxLite.
  Provider unit tests run without it. The installed-SDK contract tests in
  `backend/tests/test_boxlite_recovery_sdk.py` replace only the native runtime
  boundary and require the optional extra on a supported SDK platform; they
  must not depend on external audit files or a live hypervisor.
