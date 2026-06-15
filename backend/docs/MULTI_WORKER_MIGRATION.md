# Multi-Worker Migration Guide

Upgrade from single-worker to multi-worker deployment for horizontal scaling.

## Overview

Multi-worker mode enables running multiple Gateway instances behind a load balancer, with shared state via PostgreSQL and Redis. This provides:

- **Horizontal scaling**: Handle more concurrent users by adding workers
- **High availability**: If one worker crashes, others continue serving
- **Zero-downtime deploys**: Roll out new versions without interrupting active sessions

## Prerequisites

| Requirement | Single-worker | Multi-worker |
|---|---|---|
| Database | SQLite or Memory | **PostgreSQL 16+** |
| Cache / Coordination | None | **Redis 7+** |
| Stream bridge | Memory | **Redis** |
| Connection pool | 5 per pool | 10 per pool |

## Step-by-Step Upgrade

### 1. Start PostgreSQL and Redis

```bash
# Development
docker compose -f docker/docker-compose.dev.yml up -d

# Production (included in main compose)
docker compose -f docker/docker-compose.yaml up -d postgres redis
```

### 2. Update config.yaml

Set the deployment mode:

```yaml
deployment:
  mode: multi_worker
```

Or use the environment variable:

```bash
export DEER_FLOW_MULTI_WORKER=1
```

This automatically switches these subsystems to distributed backends:

| Subsystem | Setting | Value |
|---|---|---|
| Database | `database.backend` | `postgres` |
| Stream bridge | `stream_bridge.type` | `redis` |
| Rate limiter | `rate_limit.backend` | `redis` |
| KB indexing | `indexing.dispatcher_mode` | `queue` |
| IM coordination | `im.coordination_mode` | `redis` |

### 3. Set environment variables

In `.env`:

```bash
# PostgreSQL
DATABASE_URL=postgresql://deerflow:deerflow@localhost:5432/deerflow

# Redis
REDIS_URL=redis://localhost:6379/0
```

### 4. Run database migrations

```bash
cd backend
PYTHONPATH=. uv run alembic -c packages/harness/deerflow/persistence/alembic.ini upgrade head
```

### 5. Start multiple workers

```bash
# Using uvicorn multi-process mode
uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001 --workers 4 --timeout-graceful-shutdown 30
```

Or with Docker Compose (set `GATEWAY_WORKERS=4` in `.env`).

### 6. Verify

```bash
# Check health endpoints
curl http://localhost:8001/health/live     # Liveness probe
curl http://localhost:8001/health/ready    # Readiness probe (checks PG + Redis)
curl http://localhost:8001/health/metrics  # Prometheus metrics
```

## What Changes in Multi-Worker Mode

### Agent Memory
- Storage switches from local files to `StoreMemoryStorage` (PostgreSQL-backed)
- Concurrent writes from different workers are merged via optimistic locking (fact dedup by content key)

### KB Indexing
- Index jobs are stored in PostgreSQL (`index_jobs` table)
- Workers compete for jobs via `SELECT ... FOR UPDATE SKIP LOCKED`
- Stale jobs (worker crashed mid-index) are automatically reclaimed

### IM Channels
- Only one worker consumes each IM channel (Redis distributed lock)
- Lock auto-renews every 10 seconds; expires after 30 seconds if worker dies
- Webhook dedup prevents duplicate message processing

### SSE Streaming
- Events are published to Redis streams, readable by all workers
- Frontend reconnects via `/threads/{id}/state` if it hits a different worker

## Nginx Sticky Sessions (Optional)

When using Redis stream bridge, sticky sessions are an optimization, not a requirement. The frontend's sequence-number gap detection handles SSE recovery across workers.

To enable sticky sessions in `nginx.local.conf`:

```nginx
map $uri $thread_id {
    ~^/api/threads/([^/]+) $1;
    default "";
}

upstream gateway {
    server 127.0.0.1:8001;
    hash $thread_id consistent;
}
```

For Docker deployments using variable upstreams (for DNS resolution), sticky sessions are not applicable — use `least_conn` instead.

## Rollback

To revert to single-worker mode:

1. Set `deployment.mode: single_worker` (or unset `DEER_FLOW_MULTI_WORKER`)
2. Stop extra workers, keep one running
3. Data in PostgreSQL remains accessible — no data loss

## Connection Sizing

With 4 workers and the default pool settings:

| Pool | Per-worker | Total (4 workers) |
|---|---|---|
| Checkpointer (async) | 10 | 40 |
| App ORM | 10 + 5 overflow = 15 | 60 |
| Store | 10 | 40 |
| **Total** | | **~140** |

PostgreSQL `max_connections=250` (set in docker-compose) provides sufficient headroom.

## Dev Mode

For local development without PostgreSQL/Redis:

```bash
export DEER_FLOW_DEV_MODE=1
```

This forces all backends to memory/file/chroma. A WARNING is logged at startup.
