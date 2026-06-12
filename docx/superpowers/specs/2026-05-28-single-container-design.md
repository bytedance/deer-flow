# Single Container Deployment Design

## Context

Currently DeerFlow uses 3-container Docker Compose setup:
- nginx (port 2026)
- frontend (port 3000, Next.js dev server)
- gateway (port 8001)

This requires managing multiple containers and Docker Compose complexity. The goal is to simplify to a single container where:
- nginx + gateway run inside the container
- frontend static files (pre-built) are baked into the image

## Design

### Container Architecture

```
┌─────────────────────────────────────────┐
│        deer-flow (single container)     │
│                                         │
│  ┌─────────────┐    ┌────────────────┐  │
│  │   nginx     │───▶│    gateway     │  │
│  │  (port      │    │  (localhost    │  │
│  │   2026)     │    │    8001)       │  │
│  └─────────────┘    └────────────────┘  │
│         │                                  │
│         │ serve static files               │
│         ▼                                  │
│  /frontend/.next (baked into image)      │
└─────────────────────────────────────────┘
```

### Process Management

- **supervisord**: manages nginx + gateway processes
- `supervisord.conf` placed at `/etc/supervisord.conf` in image
- Both processes run as non-root user (www-data)

### Nginx Configuration

- Listens on `0.0.0.0:2026`
- Serves static files from `/frontend/.next`
- Proxies `/api/*` → `http://localhost:8001/api/*`
- Proxies `/api/langgraph/*` → `http://localhost:8001/api/langgraph/*`

### Dockerfile Changes

1. **New Stage: Build frontend** (before runtime stage)
   - Node.js build stage compiles `frontend/` → `frontend/.next`

2. **Stage 3 (runtime) additions**
   - Install: `supervisord`, `nginx`, `libpq5`
   - Copy: frontend static files + nginx.conf + supervisord.conf
   - Default `UV_EXTRAS=postgres,pymupdf`

3. **supervisord.conf**
   - program:nginx → `/usr/sbin/nginx -c /etc/nginx/nginx.conf`
   - program:gateway → `sh -c "cd backend && PYTHONPATH=. uv run --no-sync uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001"`

4. **Entrypoint**: `supervisord -c /etc/supervisord.conf`

### Image Build

```bash
docker build -t deer-flow:latest -f backend/Dockerfile .
```

### Data Persistence

- `backend/.deer-flow/` and `config.yaml` mounted from host:
  ```bash
  docker run -v $(pwd)/config.yaml:/app/config.yaml \
             -v $(pwd)/backend/.deer-flow:/app/backend/.deer-flow \
             -v $(pwd)/skills:/app/skills \
             -p 2026:2026 \
             deer-flow:latest
  ```

### Ports

| Port | Service | Note |
|------|---------|------|
| 2026 | nginx   | Single exposed port |

### Build Args

| Arg | Default | Purpose |
|-----|---------|---------|
| `UV_EXTRAS` | `postgres,pymupdf` | Python extras |
| `UV_INDEX_URL` | PyPI | Package index |

## Startup Flow

1. Container starts → supervisord launches
2. nginx starts (config pre-validated at build time)
3. gateway starts via `uv run uvicorn`
4. Gateway initializes LangGraph runtime, connects to checkpointer
5. All traffic through nginx:2026

## Trade-offs

**Pros**
- Single docker run command
- Simpler ops (one container to monitor/restart)
- Static files baked in → no volume complexity for frontend

**Cons**
- Longer build time (frontend build happens in Docker)
- gateway crash = both services affected (mitigated by supervisord auto-restart)
- Frontend rebuild required for any UI change (not a dev workflow)