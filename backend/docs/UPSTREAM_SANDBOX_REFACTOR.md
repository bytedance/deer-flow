# Upstream Feature: Sandbox State Management Refactor & Docker Integration

**Upstream commit:** `f836d8e17c83eb8610cb599925af5558e2138582`
**PR:** #1068
**Status:** Deferred — large 18-file commit; recommend phased integration

## Overview

This commit refactors the Docker-based sandbox (AioSandbox) system with three major themes:
1. **Simplified state management** — removes `SandboxStateStore` / `FileSandboxStateStore` abstraction in favor of in-process tracking with a warm pool
2. **Docker-outside-of-Docker (DooD) support** — enables running sandbox containers from within a Docker container by mounting the host Docker socket
3. **Infrastructure hardening** — port retry logic, directory permissions, pinned uv version, improved error handling

## Detailed Changes

### 1. State Store Removal & Warm Pool

**Removed files:**
- `backend/src/community/aio_sandbox/file_state_store.py` (102 lines)
- `backend/src/community/aio_sandbox/state_store.py` (70 lines)

**What they did:** Persisted thread→sandbox mappings to disk (JSON files) for cross-process consistency. The `SandboxStateStore` was an abstract base; `FileSandboxStateStore` stored per-thread sandbox IDs as JSON in the base directory.

**Replacement:** The `AioSandboxProvider` now tracks everything in-process:
- `_thread_sandboxes: dict[str, str]` — thread_id → sandbox_id mapping
- `_warm_pool: dict[str, tuple[SandboxInfo, float]]` — released sandboxes still running, keyed by sandbox_id with release timestamp
- File-based cross-process locking replaced by `fcntl.flock()` advisory locks

**Warm pool pattern:**
- When a sandbox is released, it goes into `_warm_pool` instead of being destroyed
- Next `acquire()` checks the warm pool first (instant reuse, no cold-start)
- When `replicas` capacity is exceeded, oldest warm pool entries are evicted and destroyed
- New config option: `replicas: 3` (max concurrent sandbox containers, LRU eviction)

**Impact on our fork:** Our `AioSandboxProvider` has additional `user_id`-based quota logic. The warm pool pattern is orthogonal and could be adopted, but the state store removal changes the acquire/release lifecycle significantly. Needs careful re-integration.

### 2. Docker-outside-of-Docker (DooD) Support

**Problem:** When the backend itself runs inside Docker, sandbox containers need to be started via the host's Docker daemon (by mounting `/var/run/docker.sock`). But volume mount paths must reference the *host* filesystem, not the container's filesystem.

**Solution:**
- New environment variable: `DEER_FLOW_HOST_BASE_DIR` — the host-side path to the backend's base directory
- `Paths` class gains `host_base_dir` property: returns `DEER_FLOW_HOST_BASE_DIR` if set, otherwise falls back to the normal `base_dir`
- `_get_thread_mounts()` uses `host_base_dir` for mount sources so the host Docker daemon can resolve them
- Similarly, `DEER_FLOW_HOST_SKILLS_PATH` provides the host-side path to the skills directory

**New files:**
- `scripts/docker.sh` — ensures `config.yaml` and `extensions_config.json` exist before Docker Compose starts

**Dockerfile changes:**
```dockerfile
# Before: curl-pipe install
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

# After: pinned image copy (reproducible, no network)
COPY --from=ghcr.io/astral-sh/uv:0.7.20 /uv /uvx /usr/local/bin/

# New: Docker CLI for DooD
COPY --from=docker:cli /usr/local/bin/docker /usr/local/bin/docker
```

**Impact on our fork:** We don't currently run the backend inside Docker in production (local dev only). The DooD pattern is useful if we move to Docker Compose production. The Dockerfile improvements (pinned uv, Docker CLI) are independently valuable.

### 3. Infrastructure Hardening

#### Port Allocation Retry (`local_backend.py`)
```python
# Before: single attempt, fails on port collision
port = find_free_port()

# After: retry loop with up to 3 attempts
for attempt in range(max_retries):
    port = find_free_port()
    try:
        # ... start container on port
        break
    except PortInUseError:
        if attempt == max_retries - 1:
            raise
```

#### Network Binding (`utils/network.py`)
```python
# Before: binds to 127.0.0.1 (localhost only)
sock.bind(("127.0.0.1", 0))

# After: binds to 0.0.0.0 (accessible from Docker containers)
sock.bind(("0.0.0.0", 0))
```

#### Directory Permissions (`paths.py`)
```python
# New: chmod 0o777 on sandbox directories
# Ensures sandbox containers (which may run as different UIDs) can read/write
dir_path.mkdir(parents=True, exist_ok=True)
dir_path.chmod(0o777)
```

#### Sandbox Middleware Logging (`middleware.py`)
- Improved context variable management for sandbox lifecycle
- Better error messages when sandbox acquisition fails
- Cleaner release logic in `after_agent`

#### Extensions Config Error Handling (`extensions_config.py`)
- Graceful handling when `extensions_config.json` is missing or malformed
- Returns empty config instead of crashing

### 4. Config Changes

**`config.example.yaml`:**
```yaml
sandbox:
  use: src.community.aio_sandbox:AioSandboxProvider
  image: "..."
  port: 8080
  container_prefix: deer-flow-sandbox
  idle_timeout: 600
  replicas: 3          # NEW: max concurrent containers (LRU eviction)
  # Removed: auto_start, base_url (simplified to just local vs provisioner)
```

**`docker-compose-dev.yaml`:**
- Adds `/var/run/docker.sock` volume mount for DooD
- Adds `DEER_FLOW_HOST_BASE_DIR` and `DEER_FLOW_HOST_SKILLS_PATH` environment variables
- Adds `scripts/docker.sh` as entrypoint wrapper

## Files Changed (18 total)

| File | Change | Risk for Our Fork |
|------|--------|-------------------|
| `backend/Dockerfile` | Pinned uv, Docker CLI | **Low** — independently useful |
| `aio_sandbox/__init__.py` | Remove state store exports | Low |
| `aio_sandbox/aio_sandbox_provider.py` | Major rewrite: warm pool, remove state store, DooD mounts | **High** — conflicts with our user_id quota system |
| `aio_sandbox/file_state_store.py` | **Deleted** | Medium |
| `aio_sandbox/state_store.py` | **Deleted** | Medium |
| `aio_sandbox/local_backend.py` | Port retry, env var for sandbox host | **Medium** — useful improvements |
| `config/extensions_config.py` | Better error handling | **Low** — useful |
| `config/paths.py` | `host_base_dir`, chmod 0o777 | **Medium** — useful for Docker |
| `config/sandbox_config.py` | Add `replicas`, remove `auto_start`/`base_url` | Medium |
| `gateway/routers/skills.py` | Minor fix | Low |
| `sandbox/middleware.py` | Improved logging and context management | **Medium** |
| `sandbox/tools.py` | Add `logger.info` for lazy sandbox acquisition | Low (already done) |
| `utils/network.py` | `0.0.0.0` binding | **Low** — useful fix |
| `config.example.yaml` | Add `replicas`, remove deprecated options | Low |
| `docker-compose-dev.yaml` | DooD volumes and env vars | Low |
| `extensions_config.example.json` | Remove unused MCP servers | Low |
| `scripts/docker.sh` | **New** — config file check script | Low |
| `scripts/start.sh` | Updated entrypoint | Low |

## Recommended Merge Strategy

### Phase 1: Low-risk infrastructure fixes (can do now)
1. **`utils/network.py`** — change `127.0.0.1` → `0.0.0.0` in `find_free_port()` (1-line fix)
2. **`local_backend.py`** — add port retry logic (small, contained change)
3. **`backend/Dockerfile`** — pin uv version, add Docker CLI COPY
4. **`config/extensions_config.py`** — improved error handling for missing config
5. **`config/paths.py`** — add `host_base_dir` property and directory chmod

### Phase 2: Warm pool + state store removal (dedicated task)
- Requires understanding interaction with our user_id quota system in `aio_sandbox_provider.py`
- The warm pool pattern is a performance win (avoids cold-start on sandbox reuse)
- `replicas` config with LRU eviction is a cleaner model than the current approach
- Plan: adapt our provider to use warm pool while preserving per-user quota enforcement

### Phase 3: DooD support (when needed)
- Only relevant when deploying backend inside Docker
- Requires `DEER_FLOW_HOST_BASE_DIR` env var mapping
- Docker Compose changes are straightforward once Phase 2 is done

## Key Considerations

- **Breaking change:** Removes `auto_start` and `base_url` config options. Any deployment using those would need migration.
- **State persistence:** The warm pool is in-process only. If the backend restarts, all sandbox mappings are lost (containers may become orphaned). The old file-based store survived restarts. Consider whether this matters for our deployment.
- **Security:** `chmod 0o777` on sandbox directories is permissive. Acceptable for dev; may need tightening for production.
- **`fcntl.flock`:** Advisory locks are Unix-only. Not an issue for our deployment but worth noting.
