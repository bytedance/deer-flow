# Docker, nginx and provisioner

Put the `/api/threads/{thread_id}/browser/stream` WebSocket regex before the
generic threads regex in Docker, local, and Helm configs.
`backend/tests/test_nginx_browser_websocket.py` pins upgrade headers and the
600s read timeout. Helm uses nginx defaults for Gateway connect/send timeouts.
Keep local temp paths checkout-relative and aligned with `serve.sh` and `nginx.sh`.

Both Compose files publish nginx at `"${BIND_HOST:-127.0.0.1}:${PORT:-2026}:2026"`.
Bare `"${PORT}:2026"` binds `0.0.0.0`. Require explicit bind addresses for new
published ports. `backend/tests/test_compose_default_bind_host.py` pins both files.
Root `PORT` controls Docker ingress only. Local Next.js stays on `3000` so
`.env` cannot redirect the dev port wait. Nginx's IPv4/IPv6 `default_server`
and Gateway's `0.0.0.0:8001` stay container-internal. Only published nginx is external.

Provisioner PVC mode declares `USERDATA_PVC_NAME` once as `user-data`; extra and
Lark broker credential mounts reuse it with their existing subPaths and read-only
flags. Keep credential mounts broker-only and keep distinct volumes in hostPath mode.

Production uses image Python (`uv run --no-sync`) and `exec` for SIGTERM;
Compose sets `init: true` (`backend/tests/test_gateway_sigterm_delivery.py`).
`make up` waits for Gateway `/health`; failures show Compose status and Gateway logs.

Docker logs/restarts resolve `DEER_FLOW_ROOT` from this checkout before Compose,
as start/stop do.
