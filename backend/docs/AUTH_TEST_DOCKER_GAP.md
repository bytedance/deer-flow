# Docker Test Gap (Section 七 7.4)

This file documents the only **un-executed** test cases from
`backend/docs/AUTH_TEST_PLAN.md` after the full release validation pass.

## Why this gap exists

The release validation environment (sg_dev: `10.251.229.92`) **does not have
a Docker daemon installed**. The TC-DOCKER cases are container-runtime
behavior tests that need an actual Docker engine to spin up
`docker/docker-compose.yaml` services.

```bash
$ ssh sg_dev "which docker; docker --version"
# (empty)
# bash: docker: command not found
```

All other test plan sections were executed against either:
- The local dev box (Mac, all services running locally), or
- The deployed sg_dev instance (gateway + frontend + nginx via SSH tunnel)

## Cases not executed

| Case | Title | What it covers | Why not run |
|---|---|---|---|
| TC-DOCKER-01 | `users.db` volume persistence | Verify the `DEER_FLOW_HOME` bind mount survives container restart | needs `docker compose up` |
| TC-DOCKER-02 | Session persistence across container restart | `AUTH_JWT_SECRET` env var keeps cookies valid after `docker compose down && up` | needs `docker compose down/up` |
| TC-DOCKER-03 | Per-worker rate limiter divergence | Confirms in-process `_login_attempts` dict doesn't share state across `gunicorn` workers (4 by default in the compose file); known limitation, documented | needs multi-worker container |
| TC-DOCKER-04 | IM channels skip AuthMiddleware | Verify Feishu/Slack/Telegram dispatchers run in-container against `http://langgraph:2024` without going through nginx | needs `docker logs` |
| TC-DOCKER-05 | Admin credentials surfacing | **Updated post-simplify** — was "log scrape", now "0600 credential file in `DEER_FLOW_HOME`". The file-based behavior is already validated by TC-1.1 + TC-UPG-13 on sg_dev (non-Docker), so the only Docker-specific gap is verifying the volume mount carries the file out to the host | needs container + host volume |
| TC-DOCKER-06 | Gateway-mode Docker deploy | `./scripts/deploy.sh --gateway` produces a 3-container topology (no `langgraph` container); same auth flow as standard mode | needs `docker compose --profile gateway` |

## Coverage already provided by non-Docker tests

The **auth-relevant** behavior in each Docker case is already exercised by
the test cases that ran on sg_dev or local:

| Docker case | Auth behavior covered by |
|---|---|
| TC-DOCKER-01 (volume persistence) | TC-REENT-01 on sg_dev (admin row survives gateway restart) — same SQLite file, just no container layer between |
| TC-DOCKER-02 (session persistence) | TC-API-02/03/06 (cookie roundtrip), plus TC-REENT-04 (multi-cookie) — JWT verification is process-state-free, container restart is equivalent to `pkill uvicorn && uv run uvicorn` |
| TC-DOCKER-03 (per-worker rate limit) | TC-GW-04 + TC-REENT-09 (single-worker rate limit + 5min expiry). The cross-worker divergence is an architectural property of the in-memory dict; no auth code path differs |
| TC-DOCKER-04 (IM channels skip auth) | Code-level only: `app/channels/manager.py` uses `langgraph_sdk` directly with no cookie handling. The langgraph_auth handler is bypassed by going through SDK, not HTTP |
| TC-DOCKER-05 (credential surfacing) | TC-1.1 on sg_dev (file at `~/deer-flow/backend/.deer-flow/admin_initial_credentials.txt`, mode 0600, password 22 chars) — the only Docker-unique step is whether the bind mount projects this path onto the host, which is a `docker compose` config check, not a runtime behavior change |
| TC-DOCKER-06 (gateway-mode container) | Section 七 7.2 covered by TC-GW-01..05 + Section 二 (gateway-mode auth flow on sg_dev) — same Gateway code, container is just a packaging change |

## Reproduction steps when Docker becomes available

Anyone with `docker` + `docker compose` installed can reproduce the gap by
running the test plan section verbatim. Pre-flight:

```bash
# Required on the host
docker --version           # >=24.x
docker compose version     # plugin >=2.x

# Required env var (otherwise sessions reset on every container restart)
echo "AUTH_JWT_SECRET=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" \
  >> .env

# Optional: pin DEER_FLOW_HOME to a stable host path
echo "DEER_FLOW_HOME=$HOME/deer-flow-data" >> .env
```

Then run TC-DOCKER-01..06 from the test plan as written.

## Decision log

- **Not blocking the release.** The auth-relevant behavior in every Docker
  case has an already-validated equivalent on bare metal. The gap is purely
  about *container packaging* details (bind mounts, multi-worker, log
  collection), not about whether the auth code paths work.
- **TC-DOCKER-05 was updated in place** in `AUTH_TEST_PLAN.md` to reflect
  the post-simplify reality (credentials file → 0600 file, no log leak).
  The old "grep 'Password:' in docker logs" expectation would have failed
  silently and given a false sense of coverage.
