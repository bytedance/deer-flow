# Docker, nginx and provisioner (`docker/`)

Compose files, nginx configuration and the sandbox provisioner. The Helm chart
in `deploy/helm/` carries the same nginx routes.

```bash
cd backend && python -m pytest tests -q -k "nginx or compose or sigterm"
```

- **Place the browser-stream WebSocket location before the generic threads
  location** in the Docker, local and Helm nginx configs. nginx takes the first
  matching regex.
- **Publish a port with an explicit bind address.** A bare `"${PORT}:2026"`
  binds `0.0.0.0`. Both Compose files default the host to `127.0.0.1`. Only the
  published nginx port is external.
- **The root `PORT` controls Docker ingress only.** Local Next.js stays on
  `3000`, so a value in `.env` cannot redirect the wait for the dev port.
- **Production starts the Gateway with the image's Python and `exec`**, and
  Compose sets `init: true`, so SIGTERM reaches the Gateway.
- **In PVC mode the provisioner declares the user-data volume once.** Extra
  mounts and Lark broker credential mounts reuse it with their own sub-paths.
  Credential mounts stay broker-only, and hostPath mode keeps distinct volumes.
- **Keep local temp paths relative to the checkout** and aligned with
  `scripts/serve.sh` and `scripts/nginx.sh`. Docker log and restart commands
  resolve `DEER_FLOW_ROOT` from the checkout before they call Compose, the same
  as start and stop.
