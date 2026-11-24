# DeerFlow loopback redirect plan

## Scope

Keep the browser origin canonicalization from #6156 on the frontend catch-all. Requests routed to the Gateway, including health probes, should retain the original host. Move the existing redirect in the Docker, local development and Helm Nginx configurations.

1. Update the existing loopback regression to check the scope of the redirect in all three configurations.
2. Move the redirect to the frontend location and run the Nginx configuration suites.
3. Verify the local development routes on a running Nginx with isolated loopback listeners and frontend and Gateway stubs.

## Verification

- Base: `ec189ccd2b258511cc9367c33520e03c047cd350`.
- Before the fix, all three new configuration assertions failed, while 52 existing cases passed. Nginx also returned `301` for `/health`, `/api/models` and `/api/langgraph/models` when reached via `127.0.0.1`.
- After the fix, the Nginx suites returned 100 passed and 2 skipped using `uv run --locked --no-sync pytest -q` from `backend`. Ruff lint, Ruff formatting and the Git whitespace check passed.
- Nginx 1.28.3 on WSL2 passed the local configuration syntax check. Requests via IPv4 and IPv6 numeric loopback returned `301` for frontend navigation, preserving the query and port, and `200` from the Gateway stub for health and API routes. Requests via `localhost` reached the frontend and Gateway stubs. `HEAD` and the Upgrade-header routing probe also passed.
- Docker Compose, a running Helm deployment, the full backend suites and `tests/blocking_io` were outside this verification run.
