# Startup diagnostics

Select the way you intend to launch DeerFlow. These opt-in probes supplement the
existing setup checks; ordinary `make doctor` and `make support-bundle` retain
their existing behavior.

```bash
make doctor STARTUP_MODE=docker
make support-bundle STARTUP_MODE=docker
# Or check the local Gateway, frontend and nginx ports:
make doctor STARTUP_MODE=local
```

The same flags work directly from the checkout root, including in PowerShell:

```bash
uv run --no-sync --project backend python scripts/doctor.py --startup-mode docker
uv run --no-sync --project backend python scripts/support_bundle.py --startup-mode docker
```

The bundle's startup checks do not require `--include-doctor` or a working
Gateway. `--include-doctor` separately captures the existing full setup report.
No model API requests are made by the startup probes.

## Choose the correct probe target

The default bind target is **127.0.0.1:2026**. The probes do not parse `.env`,
Compose files, or launcher environment precedence. If you changed Docker's
published `PORT` or `BIND_HOST`, pass the effective values explicitly:

```bash
make doctor STARTUP_MODE=docker STARTUP_HOST=0.0.0.0 STARTUP_PORT=3026
uv run --no-sync --project backend python scripts/support_bundle.py --startup-mode docker --startup-host 0.0.0.0 --startup-port 3026
```

Only numeric IPv4/IPv6 bind addresses are accepted. Local mode checks nginx on
the requested address at port 2026, plus Next.js at 127.0.0.1:3000 and the Gateway
at 127.0.0.1:8001. Its port cannot be changed with `--startup-port`.

Docker mode checks the selected engine and Compose 2.24+, then the published
port. It respects the Docker CLI's `DOCKER_CONTEXT`/`DOCKER_HOST` selection.
For TCP/SSH or an unknown endpoint, local port checks are skipped: run the port
diagnostic on the deployment host instead. Container-internal ports are not
host-port requirements. Host nginx is not required in Docker mode.

## Interpret the results

| Finding | Meaning and next step |
| --- | --- |
| `docker_cli_missing` | `docker` is absent from PATH. Install the CLI/Desktop or fix PATH and reopen the terminal. |
| `docker_desktop_not_running` | The selected local engine is unreachable and the Windows process probe did not find Docker Desktop. If you use Desktop, open it and wait for its Linux engine. Standalone Engine users should check their service/context. This does not prove Desktop is installed. |
| `docker_engine_unavailable` | CLI exists, but the engine failed or timed out. Check context, access permissions and engine health. An open Desktop window alone is not engine readiness. |
| `docker_engine` failure | The selected engine reports Windows containers; DeerFlow images need Linux containers. Switch to a Linux engine. Unknown platform output is a warning. |
| `docker_compose` failure | Compose 2.24+ was not confirmed; update or install the v2 plugin. |
| `port_in_use` | Advisory warning: the listener may be your existing DeerFlow instance. Inspect it before stopping anything; reuse the instance or choose another Docker published port. Windows reports matching listener PIDs when available. |
| `port_access_denied` | Binding was refused without a confirmed matching listener. An exclusive listener, reserved port or host policy may be responsible. On Windows inspect excluded/reserved ranges and listener state; the error alone cannot establish the cause. |
| `port_available` | A temporary bind succeeded. This is a point-in-time check, not a reservation or proof that the application will start. |

Each subprocess probe has a five-second timeout. PID attribution is best effort;
Windows commands can be unavailable or access restricted. Local mode never
requires Docker. The probes do not start/stop services, kill processes, change
WSL, delete sockets, reset Docker data or claim that a failed engine's root
cause has been established.

### Docker Desktop socket errors on Windows

If Desktop reports `The file cannot be accessed by the system` while renaming
an `engine.sock` or `sailor-ingest.sock`, the engine diagnostic will show it as
unavailable rather than assuming that the CLI's presence means Docker is ready.
Check Desktop's Troubleshoot panel; if using its WSL 2 backend, inspect
`wsl --status`. Save ongoing work before manually restarting Docker Desktop.
Collect Docker's own diagnostics if the problem persists. These checks do not
identify a socket lock owner and do not automatically delete socket directories
or reset your containers/volumes.

## Share a diagnostic bundle

With `--startup-mode`, the zip includes `startup.json`, and `triage.json` and
the issue summary include the same findings and reporter next steps.
Failed probes set the `startup_failed` active signal; warnings alone do not.
Review the summary before sharing it. Startup evidence includes probe mode, explicit
bind IP/port, fixed diagnostic messages and optional numeric listener PIDs.
Raw Docker endpoints, command stderr, process command lines and environment
values are omitted; the bundle also applies its existing redaction pipeline.
