# BoxLite provider (`deerflow/community/boxlite/`)

- **The provider owns one private asyncio loop.** New boxes and boxes recovered
  at startup execute, collect output, wait and stop on that loop, also when a
  synchronous tool worker calls. Do not use the greenlet sync SDK or
  `asyncio.run()` for a recovered handle.
- **Startup recovery only looks up existing boxes.** It lists the
  DeerFlow-prefixed names and skips missing entries.
  `SimpleBox(reuse_existing=True)` can create a VM, so it is not an attach API.
- **The recovered-box adapter keeps the semantics of `SimpleBox.exec`** for
  bytes, partial stream failures and failed waits. It drains stdout and stderr
  concurrently and waits for completion before it returns.
- **Keep SDK imports lazy.** A normal harness install does not include BoxLite,
  and the provider unit tests run without it. The installed-SDK contract tests
  replace only the native runtime boundary. They need the optional extra, and
  they do not need a live hypervisor.
