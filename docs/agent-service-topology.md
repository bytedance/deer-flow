# Service topology details

Keep the dedicated `/api/threads/{thread_id}/browser/stream` WebSocket regex before
the generic threads regex in Docker, local and Helm nginx configs. Upgrade headers
and the 600s read timeout are pinned by `backend/tests/test_nginx_browser_websocket.py`.
Helm uses nginx's default connect/send timeouts for the in-cluster Gateway.

Both Compose files publish nginx at `"${BIND_HOST:-127.0.0.1}:${PORT:-2026}:2026"`
(README's **loopback default**); bare `"${PORT}:2026"` binds `0.0.0.0`. Root `PORT`
controls Docker ingress only; local Next.js stays on `3000` so `.env` cannot
redirect `make dev`'s port wait. Nginx's IPv4+IPv6 `default_server` and Gateway's
`0.0.0.0:8001` bind are container-internal; only published nginx is external.
Require explicit bind addresses for new published ports;
`backend/tests/test_compose_default_bind_host.py` pins every service in both files.

Provisioner PVC mode declares `USERDATA_PVC_NAME` once as `user-data`; extra and
Lark broker credential mounts reuse it with their existing subPaths and read-only
flags. Keep credential mounts broker-only and keep distinct volumes in hostPath mode.
