# Sandbox Efficiency Improvement Roadmap

> **Date:** 2026-03-13
> **Scope:** Background sandbox for tool usage, code execution, and file writing
> **Goal:** Higher efficiency, lower compute footprint, production-grade isolation
> **Research Sources:** Google ADK Python (`google/adk-python`), E2B, Modal, Fly.io, Blaxel, Daytona, Azure Dynamic Sessions, Kubernetes Agent Sandbox

---

## Table of Contents

- [Current Architecture Overview](#current-architecture-overview)
- [Phase 1 — Quick Wins](#phase-1--quick-wins-1-2-weeks-zero-architecture-changes)
- [Phase 2 — Warm Pool + Sandbox Reuse](#phase-2--warm-pool--sandbox-reuse-2-4-weeks)
- [Phase 3 — Async-Native Sandbox Interface](#phase-3--async-native-sandbox-interface-2-3-weeks)
- [Phase 4 — Write Scripts to Sandbox, Not Host](#phase-4--write-scripts-to-sandbox-not-host-1-2-weeks)
- [Phase 5 — Replace File-Based State Store](#phase-5--replace-file-based-state-store-2-3-weeks)
- [Phase 6 — Isolation Technology Upgrade](#phase-6--isolation-technology-upgrade-4-8-weeks)
- [Phase 7 — Adopt Google ADK Patterns](#phase-7--adopt-google-adk-patterns-ongoing)
- [Impact vs. Effort Matrix](#impact-vs-effort-matrix)
- [Appendix A — Current Performance Characteristics](#appendix-a--current-performance-characteristics)
- [Appendix B — Google ADK Executor Comparison](#appendix-b--google-adk-executor-comparison)

---

## Current Architecture Overview

The sandbox system uses a **provider + strategy** abstraction:

```
SandboxProvider (abstract)
├── LocalSandboxProvider   → subprocess execution (dev)
├── AioSandboxProvider     → Docker/K8s containers (production)
│   ├── LocalContainerBackend   → auto-starts Docker containers
│   └── RemoteSandboxBackend    → connects to K8s provisioner
└── DaytonaSandboxProvider → cloud-managed sandboxes (community)
```

**Key files:**

| File | LOC | Purpose |
|------|-----|---------|
| `sandbox/sandbox.py` | 72 | Abstract Sandbox interface |
| `sandbox/sandbox_provider.py` | 100 | Abstract SandboxProvider + singleton factory |
| `sandbox/tools.py` | 448 | 6 core tools (bash, execute_python, ls, read/write_file, str_replace) |
| `sandbox/code_execution.py` | 119 | execute_python implementation |
| `sandbox/middleware.py` | 72 | SandboxMiddleware for lifecycle management |
| `sandbox/local/local_sandbox.py` | 203 | LocalSandbox (subprocess-based) |
| `sandbox/local/local_sandbox_provider.py` | 64 | LocalSandboxProvider (singleton) |
| `community/aio_sandbox/aio_sandbox_provider.py` | 531 | AioSandboxProvider (pluggable backends, state store, idle management) |
| `community/aio_sandbox/aio_sandbox.py` | ~150 | AioSandbox (HTTP client wrapper) |
| `docker/provisioner/app.py` | 681 | K8s provisioner FastAPI app |

---

## Phase 1 — Quick Wins (1-2 weeks, zero architecture changes)

Pure code fixes in existing files that yield immediate performance gains.

### 1.1 Cache Compiled Regexes

**Problem:** `replace_virtual_paths_in_command()` recompiles regex patterns on every single tool call. `_resolve_paths_in_command()` and `_reverse_resolve_paths_in_output()` do the same.

**Fix:** Compile patterns once at module level or in `__init__`.

**Files:** `tools.py`, `local_sandbox.py`

**Impact:** ~5-10% faster per tool call.

### 1.2 Cache Sorted Path Mappings

**Problem:** `_resolve_path()` and `_reverse_resolve_path()` call `sorted()` on the path mappings dictionary on every invocation.

**Fix:** Compute the sorted key list once in `__init__` and invalidate only if mappings change.

**Files:** `local_sandbox.py` (lines ~36, 59, 83, 119)

**Impact:** Eliminates O(n log n) sorting on every file operation.

### 1.3 Cache Shell Detection

**Problem:** `_get_shell()` runs filesystem checks (`os.path.isfile`, `os.access`) on every command execution to detect `zsh` vs `bash` vs `sh`.

**Fix:** Detect once at startup, store in instance variable.

**Files:** `local_sandbox.py` (lines ~136-153)

**Impact:** Eliminates N filesystem stat calls per session.

### 1.4 Add Output Truncation to `bash` Tool

**Problem:** The `bash` tool returns unbounded output. An agent running `cat large_file.csv` can return megabytes and overwhelm the LLM context window. The `execute_python` tool already limits output to 4096 chars — `bash` should match.

**Fix:** Apply the same truncation logic to `bash` output.

**Files:** `tools.py`

**Impact:** Prevents context overflow and runaway token costs.

### 1.5 Tail-Weighted Truncation

**Problem:** Current truncation takes the *first* 4096 characters. Errors, return values, and final output are usually at the *end* of command output.

**Fix:** Keep first 1K + last 3K (head + tail) so agents can see both the start of output and the most actionable end.

**Files:** `code_execution.py` (lines ~101-114)

**Impact:** Dramatically better error visibility for agents.

### 1.6 DRY Out Tool Boilerplate

**Problem:** Every tool function repeats the same preamble: `ensure_sandbox_initialized`, `ensure_thread_directories_exist`, path replacement, error handling.

**Fix:** Extract into a decorator (e.g., `@sandbox_tool`) that handles initialization, path resolution, and error wrapping.

**Files:** `tools.py` (lines ~275-448)

**Impact:** Reduced code duplication, smaller bug surface, easier to add new tools.

### 1.7 Fix `str_replace` Error Detection

**Problem:** Uses `startswith("Error:")` string matching to check for failures. A file legitimately starting with the text `"Error:"` would cause silent data loss.

**Fix:** Use proper exception-based error propagation from the sandbox.

**Files:** `aio_sandbox.py` (line ~109)

**Impact:** Prevents data corruption edge case.

### 1.8 Thread-Safe Singleton Creation

**Problem:** `get_sandbox_provider()` has a check-then-act race condition. Two threads could simultaneously see `_singleton is None` and create duplicate providers.

**Fix:** Add a `threading.Lock` around the singleton creation.

**Files:** `sandbox_provider.py` (lines ~43-60)

**Impact:** Prevents duplicate provider instances under concurrent load.

---

## Phase 2 — Warm Pool + Sandbox Reuse (2-4 weeks)

> **This is the single highest-impact architectural change.** Cold starts (5-10s Docker, 30s+ K8s) are the #1 user-facing bottleneck.

### Industry Benchmarks

| Platform | Technique | Allocation Time |
|----------|-----------|-----------------|
| E2B | Firecracker snapshot pool | <200ms |
| Blaxel | Firecracker standby resume | 25ms |
| Azure Dynamic Sessions | Pre-warmed container pool | <500ms |
| K8s Agent Sandbox | `SandboxWarmPool` CRD | 90% faster |
| Google ADK | Session-state sandbox reuse (no warm pool) | 5-10s cold start |
| **Our current** | **Create on demand** | **5-10s Docker, 30s+ K8s** |

### Design

```
┌─────────────────────────────────────────────────────┐
│                  Warm Pool Manager                   │
│                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐          │
│  │ Ready #1 │  │ Ready #2 │  │ Ready #3 │  ...     │
│  │ (idle)   │  │ (idle)   │  │ (idle)   │          │
│  └──────────┘  └──────────┘  └──────────┘          │
│       │                                             │
│       ▼  acquire(thread_id) → instant assignment    │
│  ┌──────────┐                                       │
│  │ Active   │ ──→ idle timeout ──→ back to pool    │
│  │ sandbox  │                     (not destroyed)   │
│  └──────────┘                                       │
│                                                     │
│  Background: replenish pool to target size          │
└─────────────────────────────────────────────────────┘
```

### Implementation Plan

1. **Add `WarmPoolManager` class** alongside `AioSandboxProvider`
   - Configurable `warm_pool_size` (default: 3)
   - Background thread pre-starts containers to maintain pool target
   - Thread-safe queue for ready containers (`asyncio.Queue` or `queue.Queue`)

2. **Modify `acquire()` flow**
   - Try pool first → instant assignment (<100ms)
   - Pool empty → fall back to on-demand creation (current behavior)
   - Log pool miss rate for monitoring

3. **Modify `release()` flow**
   - Instead of destroying: reset container state (clear `/mnt/user-data/`)
   - Return container to pool if pool is below target size
   - Destroy if pool is at capacity

4. **Store sandbox IDs in session state** (adopt from Google ADK)
   - `AgentEngineSandboxCodeExecutor` stores sandbox resource names in session state for cross-invocation reuse
   - Apply same pattern: `runtime.state["sandbox"]["sandbox_id"]` persists across turns (already partially implemented)

5. **Configuration** (`config.yaml`):
   ```yaml
   sandbox:
     warm_pool:
       enabled: true
       target_size: 3
       max_size: 10
       replenish_interval: 30  # seconds
       reset_command: "rm -rf /mnt/user-data/* && echo 'ready'"
   ```

### Expected Impact

| Metric | Before | After |
|--------|--------|-------|
| First tool call latency | 5-10s | <100ms (pool hit) |
| Pool miss rate (target) | N/A | <10% |
| Resource overhead | 0 idle containers | 3 idle containers (~1.5 GiB) |

---

## Phase 3 — Async-Native Sandbox Interface (2-3 weeks)

### Problem

The entire `Sandbox` interface is synchronous. Every HTTP call to the AIO container blocks a thread. In LangGraph's async runtime, this causes thread-pool exhaustion under concurrent load.

### What Google ADK Does

- Tool execution uses `asyncio.gather()` for parallel tool calls
- `_invoke_callable()` handles both sync and async functions transparently
- Thread pools are cached globally with lazy initialization and lock protection
- Global `_TOOL_THREAD_POOLS` dictionary keyed by worker count

### New Interface

```python
from dataclasses import dataclass
from abc import ABC, abstractmethod
from typing import Optional

@dataclass
class CommandResult:
    """Structured result instead of concatenated strings."""
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool = False

class Sandbox(ABC):
    @abstractmethod
    async def execute_command(
        self, command: str, timeout: int = 60
    ) -> CommandResult:
        ...

    @abstractmethod
    async def read_file(self, path: str) -> str:
        ...

    @abstractmethod
    async def write_file(
        self, path: str, content: str, append: bool = False
    ) -> None:
        ...

    @abstractmethod
    async def list_dir(
        self, path: str, max_depth: int = 2
    ) -> list[str]:
        ...

    async def file_exists(self, path: str) -> bool:
        """Avoid wasteful read-to-check patterns."""
        try:
            await self.read_file(path)
            return True
        except FileNotFoundError:
            return False

    async def execute_batch(
        self, operations: list["SandboxOp"]
    ) -> list["SandboxResult"]:
        """Execute multiple operations in a single round-trip.
        Override in AioSandbox to send batch HTTP requests."""
        return [await op.execute(self) for op in operations]
```

### Key Changes

| Change | Rationale |
|--------|-----------|
| `async def` everywhere | Use `httpx.AsyncClient` in AioSandbox; no thread blocking |
| `CommandResult` dataclass | Separate stdout/stderr/exit_code instead of concatenated strings |
| Configurable timeout per op | Remove hardcoded 600s; let callers choose |
| `execute_batch()` | Reduce HTTP round-trips for multi-step tool sequences |
| `file_exists()` | Avoid read-to-check anti-pattern |

### Migration Path

1. Add async methods alongside sync ones (dual interface)
2. Update tools to use async versions
3. Deprecate sync methods
4. Remove sync methods in next major version

---

## Phase 4 — Write Scripts to Sandbox, Not Host (1-2 weeks)

### Problem

`code_execution.py` writes temporary Python scripts to the *host* filesystem (`os.makedirs`, `open(script_path, "w")`), then expects them to be visible inside the container via volume mounts. This:

- Creates race conditions with filesystem sync
- Doesn't work with remote sandboxes (no shared volume)
- Leaves temp files on the host

### What Google ADK Does

- `ContainerCodeExecutor`: Passes code inline via `container.exec_run(['python3', '-c', code])` — no temp files at all
- `GkeCodeExecutor`: Passes code via Kubernetes ConfigMaps — first-class K8s primitive

### Fix

```python
async def execute_python(sandbox: Sandbox, code: str) -> str:
    """Execute Python code entirely within the sandbox."""
    script_path = f"/tmp/_exec_{uuid.uuid4().hex[:8]}.py"
    await sandbox.write_file(script_path, code)
    result = await sandbox.execute_command(
        f"python3 {script_path}", timeout=120
    )
    # Cleanup inside the sandbox
    await sandbox.execute_command(f"rm -f {script_path}")
    return result
```

### Alternative: Inline Execution (Google ADK approach)

```python
async def execute_python(sandbox: Sandbox, code: str) -> str:
    """Pass code inline — no temp files at all."""
    # Escape single quotes in code for shell safety
    escaped = code.replace("'", "'\\''")
    result = await sandbox.execute_command(
        f"python3 -c '{escaped}'", timeout=120
    )
    return result
```

**Trade-off:** Inline execution is simpler but breaks for large scripts (shell argument length limits). The temp-file-in-sandbox approach is more robust.

---

## Phase 5 — Replace File-Based State Store (2-3 weeks)

### Problem

`FileSandboxStateStore` uses `fcntl.flock` file locks for cross-process coordination:

- **Platform-specific:** No Windows support
- **Single-host only:** Cannot coordinate across multiple backend instances
- **Stale locks:** `.lock` files accumulate on crashes
- **I/O bottleneck:** File read/write for every state check

### Options

| Store | Latency | Multi-Host | Complexity |
|-------|---------|------------|------------|
| FileSandboxStateStore (current) | ~1-5ms | No | Low |
| **SQLite with WAL** | ~0.5ms | No | Low |
| **Redis** | ~1ms | Yes | Medium |
| PostgreSQL (existing in stack) | ~2ms | Yes | Medium |

### Recommended: Redis for Production

```python
import redis
from contextlib import contextmanager

class RedisSandboxStateStore(SandboxStateStore):
    """Redis-backed state store for multi-host deployments."""

    def __init__(self, redis_url: str, ttl: int = 3600):
        self.redis = redis.from_url(redis_url)
        self.ttl = ttl

    def load(self, thread_id: str) -> SandboxInfo | None:
        data = self.redis.get(f"sandbox:{thread_id}")
        return SandboxInfo.from_json(data) if data else None

    def save(self, thread_id: str, info: SandboxInfo) -> None:
        self.redis.setex(
            f"sandbox:{thread_id}", self.ttl, info.to_json()
        )

    def delete(self, thread_id: str) -> None:
        self.redis.delete(f"sandbox:{thread_id}")

    @contextmanager
    def lock(self, thread_id: str, timeout: int = 30):
        lock = self.redis.lock(
            f"sandbox:lock:{thread_id}", timeout=timeout
        )
        try:
            lock.acquire()
            yield
        finally:
            lock.release()

    def list_all(self) -> dict[str, SandboxInfo]:
        keys = self.redis.keys("sandbox:*")
        result = {}
        for key in keys:
            if b":lock:" not in key:
                data = self.redis.get(key)
                if data:
                    tid = key.decode().split(":", 1)[1]
                    result[tid] = SandboxInfo.from_json(data)
        return result
```

### Recommended: SQLite for Single-Host

```python
class SQLiteSandboxStateStore(SandboxStateStore):
    """SQLite with WAL mode for single-host deployments."""

    def __init__(self, db_path: str = ".think-tank/sandbox_state.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sandbox_state (
                thread_id TEXT PRIMARY KEY,
                sandbox_info TEXT NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        conn.commit()
        conn.close()
```

### Configuration

```yaml
sandbox:
  state_store: redis            # Options: file, sqlite, redis
  redis_url: redis://localhost:6379/0
  state_ttl: 3600               # seconds
```

---

## Phase 6 — Isolation Technology Upgrade (4-8 weeks)

### Technology Comparison

```
                    Startup    Memory      Isolation    Complexity
                    ─────────  ──────────  ───────────  ──────────
Current (Docker)    5-10s      512 MiB     Namespace    Low
+ Warm Pool         <100ms     512 MiB     Namespace    Medium

gVisor (runsc)      50-100ms   ~30 MiB     User kernel  Medium
+ Snapshots         ~0.5s      ~30 MiB     User kernel  Medium

Firecracker         100-200ms  <5 MiB      Hardware VM  High
+ Snapshots         4-25ms     <5 MiB      Hardware VM  High

nsjail              ~10ms      ~0          Namespace+   Low
                                           seccomp
```

### Recommended Path by Deployment

| Deployment | Recommended | Why |
|------------|-------------|-----|
| **Local dev** | Keep `LocalSandbox` | Zero overhead, developer convenience |
| **Self-hosted production** | **gVisor (`runsc`)** | Drop-in replacement for Docker runtime; same OCI images; used by Modal and Google Cloud |
| **Multi-tenant SaaS** | **Firecracker + snapshots** | VM-level isolation; 4-25ms restore; <5 MiB per sandbox; used by E2B and AWS Lambda |

### 6.1 gVisor Integration (Easiest Upgrade)

gVisor is a **drop-in Docker runtime replacement** — no image changes needed.

**Docker Compose:**
```yaml
services:
  sandbox:
    runtime: runsc          # ← gVisor runtime (replaces runc)
    image: your-sandbox-image
```

**Kubernetes (used by Google ADK's GkeCodeExecutor):**
```yaml
spec:
  runtimeClassName: gvisor  # ← Google ADK uses this exact pattern
  containers:
    - name: sandbox
      securityContext:
        runAsUser: 1001
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities:
          drop: ["ALL"]
      resources:
        requests:
          cpu: 200m
          memory: 256Mi
        limits:
          cpu: 500m
          memory: 512Mi
```

**Installation:**
```bash
# Install gVisor runtime
curl -fsSL https://gvisor.dev/archive.key | sudo gpg --dearmor -o /usr/share/keyrings/gvisor-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/gvisor-archive-keyring.gpg] https://storage.googleapis.com/gvisor/releases release main" | sudo tee /etc/apt/sources.list.d/gvisor.list
sudo apt-get update && sudo apt-get install -y runsc

# Configure Docker to use gVisor
sudo runsc install
sudo systemctl restart docker
```

### 6.2 Firecracker (Maximum Efficiency)

For multi-tenant SaaS with thousands of concurrent sandboxes:

**Architecture:**
```
┌──────────────────────────────────────┐
│          Firecracker VMM             │
│                                      │
│  ┌────────────────────────────────┐  │
│  │ microVM (~5 MiB memory)       │  │
│  │ ┌──────────────────────────┐  │  │
│  │ │ Minimal Linux kernel     │  │  │
│  │ │ Python 3 + dependencies  │  │  │
│  │ │ /mnt/user-data (virtio)  │  │  │
│  │ └──────────────────────────┘  │  │
│  └────────────────────────────────┘  │
│                                      │
│  Snapshot → restore in 4-25ms        │
└──────────────────────────────────────┘
```

**Key benefit:** Create a golden snapshot with all dependencies installed. Restore from snapshot is 4-25ms with full VM-level isolation.

### 6.3 nsjail (Lightest Weight)

For maximum performance with reasonable isolation:

```python
class NsjailSandbox(Sandbox):
    """Linux namespace sandbox with near-zero overhead."""

    async def execute_command(self, command: str, timeout: int = 60) -> CommandResult:
        nsjail_cmd = [
            "nsjail",
            "--mode", "once",
            "--time_limit", str(timeout),
            "--rlimit_as", "512",           # 512 MiB address space
            "--rlimit_cpu", "30",            # 30s CPU time
            "--rlimit_fsize", "64",          # 64 MiB max file size
            "--rlimit_nproc", "64",          # 64 max processes
            "--chroot", self.rootfs_path,
            "--user", "1000:1000",
            "--cwd", "/workspace",
            "--bindmount_ro", "/usr",
            "--bindmount", f"{self.data_dir}:/mnt/user-data",
            "--", "/bin/sh", "-c", command
        ]
        proc = await asyncio.create_subprocess_exec(
            *nsjail_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
        return CommandResult(
            stdout=stdout.decode(),
            stderr=stderr.decode(),
            exit_code=proc.returncode or 0
        )
```

---

## Phase 7 — Adopt Google ADK Patterns (ongoing)

Specific patterns from `google/adk-python` worth adopting:

### 7.1 Lazy Imports for Heavy Dependencies

**ADK Pattern:** `code_executors/__init__.py` uses `__getattr__()` to dynamically import Docker, Kubernetes, and Vertex AI clients only when accessed.

**Our Fix:**
```python
# sandbox/__init__.py
_LAZY_IMPORTS = {
    "AioSandboxProvider": "src.community.aio_sandbox.aio_sandbox_provider",
    "DaytonaSandboxProvider": "src.community.daytona_sandbox",
}

def __getattr__(name):
    if name in _LAZY_IMPORTS:
        module = importlib.import_module(_LAZY_IMPORTS[name])
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```

**Impact:** Faster startup for users who don't need container execution.

### 7.2 Tiered Executor Naming

**ADK Pattern:** Executors are explicitly named by security level: `UnsafeLocalCodeExecutor`, `ContainerCodeExecutor`, `GkeCodeExecutor`.

**Our Fix:** Rename providers to signal security tier:
- `LocalSandboxProvider` → `UnsafeLocalSandboxProvider` (makes the risk explicit)
- `AioSandboxProvider` → `ContainerSandboxProvider`
- Document which deployment contexts each is appropriate for

### 7.3 Artifact Service for File I/O

**ADK Pattern:** Files are handled through a versioned `ArtifactService` with MIME types, not raw filesystem writes. Supports pluggable backends (in-memory, filesystem, GCS).

**Our Fix:** Add an artifact abstraction for outputs:
```python
class ArtifactService(ABC):
    async def save(self, key: str, data: bytes, mime_type: str) -> str: ...
    async def load(self, key: str, version: int = -1) -> bytes: ...
    async def list(self, prefix: str) -> list[ArtifactMeta]: ...
```

**Impact:** Enables cloud storage backends, versioned outputs, and proper MIME handling.

### 7.4 Parallel Tool Execution

**ADK Pattern:** `handle_function_calls_async()` creates `asyncio.Task` for each tool call and uses `asyncio.gather()` for parallel execution.

**Our Fix:** When the LLM returns multiple tool calls in one turn, execute them concurrently:
```python
async def execute_tools(tool_calls: list[ToolCall]) -> list[ToolResult]:
    tasks = [execute_single_tool(tc) for tc in tool_calls]
    return await asyncio.gather(*tasks, return_exceptions=True)
```

**Impact:** Multi-tool turns complete in `max(tool_times)` instead of `sum(tool_times)`.

### 7.5 Processor Pipeline for Cross-Cutting Concerns

**ADK Pattern:** `SingleFlow` uses ordered request/response processors for concerns like compaction, caching, and code execution pre/post-processing.

**Our Fix:** Extract path translation, output truncation, and error wrapping from individual tools into pre/post processors:
```python
class PathTranslationProcessor:
    def pre_process(self, tool_call: ToolCall) -> ToolCall:
        # Replace virtual paths in arguments
        ...

    def post_process(self, result: ToolResult) -> ToolResult:
        # Reverse-translate paths in output
        ...
```

### 7.6 Error Retry at Sandbox Level

**ADK Pattern:** `BaseCodeExecutor` has `error_retry_attempts = 2` for consecutive errors, with automatic retry tracking.

**Our Fix:** Add a retry decorator on `AioSandbox` HTTP methods:
```python
@retry(
    max_attempts=2,
    retry_on=(httpx.ConnectError, httpx.TimeoutException),
    backoff=exponential(base=1, max=5)
)
async def execute_command(self, command: str, timeout: int = 60) -> CommandResult:
    ...
```

**Impact:** Transient network failures don't kill agent workflows.

---

## Impact vs. Effort Matrix

```
Impact
  ▲
  │
  │  ★ Warm Pool (P2)        ★ Async Interface (P3)
  │
  │  ★ Quick Wins (P1)       ★ gVisor Runtime (P6)
  │
  │  ★ Script-in-Sandbox     ★ Firecracker (P6)
  │     (P4)
  │
  │  ★ Redis State (P5)      ★ ADK Patterns (P7)
  │
  └──────────────────────────────────────────► Effort
      1-2 weeks    2-4 weeks    4-8 weeks
```

### Recommended Execution Order

1. **Phase 1** — Quick wins (immediate, no risk)
2. **Phase 2** — Warm pool (biggest user-facing improvement)
3. **Phase 4** — Script-to-sandbox (prerequisite for remote sandboxes)
4. **Phase 3** — Async interface (enables concurrency)
5. **Phase 5** — Redis state store (enables multi-host)
6. **Phase 6** — gVisor or Firecracker (when scaling to multi-tenant)
7. **Phase 7** — ADK patterns (ongoing refinement)

---

## Appendix A — Current Performance Characteristics

| Scenario | Local Sandbox | AioSandbox (Docker) | AioSandbox (K8s) |
|----------|---------------|---------------------|-------------------|
| First tool call | ~0ms | ~5-10s | ~1-5s |
| Subsequent calls | ~10-50ms | ~10-50ms | ~50-200ms |
| Max per user | Unlimited | 3 (configurable) | 3 (quota enforced) |
| Sandbox lifetime | Process lifetime | 15min idle → destroy | 15min idle → destroy |
| Memory per sandbox | ~0 (shared OS) | ~512 MiB | ~512 MiB |
| Security isolation | None | Namespace | Namespace |

---

## Appendix B — Google ADK Executor Comparison

| Executor | Isolation | Stateful | Cold Start | Use Case |
|----------|-----------|----------|------------|----------|
| `UnsafeLocalCodeExecutor` | None (local `exec()`) | No | 0ms | Dev/testing only |
| `BuiltInCodeExecutor` | Model-side | N/A | 0ms | Gemini 2.0+ native |
| `ContainerCodeExecutor` | Docker container | No | 5-10s | Local sandboxed |
| `GkeCodeExecutor` | gVisor + K8s | No | 10-30s | Production GKE |
| `VertexAiCodeExecutor` | Cloud managed | Yes | <1s | Managed cloud |
| `AgentEngineSandboxCodeExecutor` | Cloud sandbox | Yes | <1s | Agent Engine |

### Key ADK Design Decisions

1. **No warm pool** — Containers created per-executor, no pooling
2. **Statelessness default** — Only cloud executors support state
3. **Code-as-string** — No AST validation or compilation
4. **File I/O via artifact service** — Not raw filesystem
5. **Separate tool vs. code execution** — Independent pipelines
6. **Stateless runner** — All persistence in services (Session, Artifact, Memory)
