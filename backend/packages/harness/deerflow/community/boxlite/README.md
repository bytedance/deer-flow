# BoxLite backend

Runs each DeerFlow sandbox as a [BoxLite](https://github.com/boxlite-ai/boxlite)
micro-VM — a daemonless, OCI-native VM with its own kernel (libkrun/KVM on Linux,
Hypervisor.framework on macOS). Motivated by the resource/cold-start pain with
the default AIO Docker sandbox in
[#3439](https://github.com/bytedance/deer-flow/issues/3439) and
[#3213](https://github.com/bytedance/deer-flow/issues/3213); discussion in
[#3936](https://github.com/bytedance/deer-flow/issues/3936).

## Configuration

```yaml
sandbox:
  use: deerflow.community.boxlite:BoxliteProvider
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
nested virtualization when DeerFlow runs inside a cloud VM. macOS uses
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
| `provider.py` | `SandboxProvider` lifecycle + the private-loop bridge |
| `box.py`      | `Sandbox` adapter; `execute_command` + file ops |

## Contract coverage

The full `Sandbox` surface is implemented. File operations run as shell commands
inside the box and reuse `deerflow.sandbox.search`, mirroring `e2b_sandbox`:

- `execute_command` — `sh -lc`, with per-call env and timeout.
- `read_file` / `write_file` / `update_file` — `cat` and chunked `base64` (binary-safe, no arg-size limit).
- `download_file` — 100 MB cap, restricted to the `/mnt/user-data` prefix.
- `list_dir` / `glob` / `grep` — `find` / `grep` with busybox-portable flags; results filtered/capped in Python.

The provider creates `/mnt/user-data/{workspace,uploads,outputs}` and
`/mnt/skills` on box start so those virtual paths resolve natively.

**Out of scope for this pass** (follow-ups): warm pooling, idle reaping, mount
syncing, and remote/provisioner modes.

## Status

Verified end-to-end against a live box (provider resolution → `execute_command`
→ file ops) on macOS/HVF. Linux/KVM validation and benchmarks vs. the AIO
sandbox are tracked in
[#3936](https://github.com/bytedance/deer-flow/issues/3936).
