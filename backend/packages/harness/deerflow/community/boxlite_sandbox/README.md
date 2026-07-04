# BoxLite sandbox provider

Runs each DeerFlow sandbox as a [BoxLite](https://github.com/boxlite-ai/boxlite)
micro-VM — a daemonless, OCI-native VM with its own kernel (libkrun/KVM on Linux,
Hypervisor.framework on macOS). Motivated by the resource/cold-start pain with
the default AIO Docker sandbox in
[#3439](https://github.com/bytedance/deer-flow/issues/3439) and
[#3213](https://github.com/bytedance/deer-flow/issues/3213).

> **Status: scaffold / RFC — [#3936](https://github.com/bytedance/deer-flow/issues/3936).**
> `execute_command` (bash) is wired end to end; the other `Sandbox` methods are
> stubbed. Opened to align on approach before hardening. Not yet benchmarked.

## Configuration

```yaml
sandbox:
  use: deerflow.community.boxlite_sandbox:BoxliteSandboxProvider
  image: python:3.12-slim   # any OCI image, run unchanged (default: python:3.12-slim)
  memory_mib: 1024          # per-box memory cap (optional)
  cpus: 2                   # per-box vCPUs (optional)
  environment:              # injected into every command
    PYTHONUNBUFFERED: "1"
```

```bash
pip install boxlite   # an optional `[boxlite]` extra + uv.lock update will follow once the approach lands
```

**Host requirement:** BoxLite boots micro-VMs, so a Linux host needs KVM — i.e.
nested virtualization when DeerFlow itself runs inside a cloud VM. macOS uses
Hypervisor.framework. This is the main deployment constraint to weigh vs. the
container-based providers.

## Design

DeerFlow's `Sandbox` contract is synchronous; BoxLite's SDK is async-native and
its box handles are event-loop-affine. The provider owns **one** private asyncio
loop on a daemon thread and marshals every coroutine onto it via
`run_coroutine_threadsafe`. This keeps all operations on the loop the box was
started on and is safe under DeerFlow's `asyncio.to_thread` worker pool — without
using BoxLite's greenlet sync facade, which refuses to run inside an async
context and is thread-affine.

| File | Role |
| --- | --- |
| `boxlite_provider.py` | `SandboxProvider` lifecycle + the private-loop bridge |
| `boxlite_sandbox.py`  | `Sandbox` adapter; `execute_command` via `sh -lc` |

## What's implemented vs. open

- **Done:** provider lifecycle (`acquire`/`get`/`release`/`shutdown`), per-thread
  reuse, `execute_command`, optional-dependency wiring.
- **Stubbed (raise `NotImplementedError`):** `read_file`, `write_file`,
  `download_file`, `update_file`, `list_dir`, `glob`, `grep`. The plan is to map
  the `/mnt/user-data` virtual prefix into the box and implement these via `exec`
  (`cat`/`tee`/`base64`) plus `deerflow.sandbox.search`, mirroring `e2b_sandbox`.
- **Out of scope for this pass:** warm pooling, idle reaping, mount syncing,
  remote/provisioner modes.

Open questions for maintainers are tracked in
[#3936](https://github.com/bytedance/deer-flow/issues/3936): host/KVM
acceptability, tool-surface parity with the AIO image, and in-tree vs. external
packaging.
