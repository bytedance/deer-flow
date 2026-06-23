# Per-User Persistent Home Mount 实施任务清单

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-user, persistent, read-write mount `/mnt/user-home/` to the sandbox so that files written in one thread survive across threads, while preserving the existing `/mnt/user-data/{workspace,uploads,outputs}` thread-scoped behaviour unchanged.

**Architecture:** One new Pydantic config block (`sandbox.user_home.{enabled,container_path}`), one new directory pair on the host (`backend/.deer-flow/users/{user_id}/home/` ↔ `/mnt/user-home/`), one new pair of `ThreadDataState` fields (`user_home_path` / `user_home_container_path`) injected by `ThreadDataMiddleware`, four entry points extended in `sandbox/tools.py` (`_thread_virtual_to_actual_mappings`, `_validate_resolved_user_data_path`, `_is_user_home_path` / `_resolve_user_home_path`, `replace_virtual_paths_in_command`), two sandbox providers extended to bind-mount the directory (`LocalSandboxProvider._build_thread_path_mappings` for local; `AioSandboxProvider._get_thread_mounts` for container-based), one startup warning emitted by the AIO provider when remote provisioning is selected with `user_home.enabled=true` (Phase 1 R5 mitigation), one new prompt section teaching the agent the three-class path model (thread/user/fact), and one `config.example.yaml` bump. Subagents inherit transparently via the existing `state["thread_data"]` passthrough (`subagents/executor.py:478-479`) — no subagent code changes.

**Tech Stack:** Python 3.12, Pydantic, LangGraph AgentMiddleware, pytest, ruff. Local sandbox uses in-process `PathMapping`. AIO sandbox uses `LocalContainerBackend.create()` with bind-mount args. Remote provisioning (k3s provisioner) is Phase 2 — Phase 1 only logs a warning.

## Global Constraints

- Backend import prefix `deerflow.*`; **never** import `app.*` from inside `packages/harness/deerflow/` (`tests/test_harness_boundary.py` runs in CI).
- All new code must be covered by unit tests in `backend/tests/test_<feature>.py` (TDD: failing test → red → impl → green → commit).
- Conventional commits only (`feat:` / `test:` / `docs:` / `chore:`); one commit per task.
- All `pytest` commands MUST be prefixed with `cd backend &&`; all `cd backend && make test` / `make lint` work as well — but in step-by-step we use the explicit `cd backend &&` form for sub-test runs.
- Bash commands must use `rtk` prefix (per repo `CLAUDE.md`).
- New Pydantic field default: `enabled=True`, `container_path="/mnt/user-home"` — Phase 1 is backward-compatible (no user config change required).
- Host-side permissions: `mkdir(parents=True, exist_ok=True)` followed by `chmod(0o777)` — same pattern as `Paths.ensure_thread_dirs` (`paths.py:335`).
- Sandbox container path: `/mnt/user-home` (configurable via `container_path`).
- R5 (AIO remote provisioning silently drops `extra_mounts`) — **Phase 1 only emits a startup warning**, does not fix the payload bug. R8 (regex truncation on quoted paths with spaces) — **Phase 1 only documents the limitation in the agent prompt**, does not modify `replace_virtual_paths_in_command`'s regexes.
- User ID resolution: ALWAYS use `deerflow.runtime.user_context.get_effective_user_id()` (no-auth fallback returns `"default"` per `DEFAULT_USER_ID = "default"` at `runtime/user_context.py:97`).
- `deerflow.config.paths` import boundary: do **not** import from `deerflow.runtime.user_context` at module top level in `paths.py`; do it inside functions (avoids cycles with `user_context` if any are added later).

## Out of Scope (explicitly NOT done in this plan)

- Fixing R5 (`remote_backend.py:135-146` payload bug) — Phase 2.
- Fixing R8 (`replace_virtual_paths_in_command` regex) — separate evaluation task.
- Implementing `delete_user_dir()` HTTP route — design calls for CLI/GDPR-only access; out of scope.
- Migrating legacy data — new feature, no migration needed.
- XDG-style subdirectory split — design Phase 3.

---

### Task 1: `paths.user_home_dir` / `host_user_home_dir` helpers

**Files:**
- Modify: `backend/packages/harness/deerflow/config/paths.py:180-187` (after `user_dir`)
- Test: `backend/tests/test_user_home_dir.py` (create)

**Interfaces:**
- Consumes: `user_id: str` (already validated by `_validate_user_id` upstream via `user_dir`).
- Produces:
  - `Paths.user_home_dir(user_id: str) -> Path` — returns `{base_dir}/users/{user_id}/home/`. Does NOT mkdir.
  - `Paths.host_user_home_dir(user_id: str) -> str` — returns the host bind-mount source string (uses `DEER_FLOW_HOST_BASE_DIR` env override if set, else `str(self.base_dir)`). Joins with native path style (Windows compat).
- Consumed by: Task 2 (config), Task 4 (middleware), Task 7-8 (sandbox providers), Task 11 (config example).

**Risks covered:** R2 (permission drift — locks to `0o777`).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_user_home_dir.py`:

```python
"""User-home directory helpers.

Each user owns a single persistent directory ``{base_dir}/users/{user_id}/home``
that is bind-mounted into the sandbox at ``/mnt/user-home``. These tests pin
down the host-side helpers added to ``deerflow.config.paths.Paths``.
"""
from __future__ import annotations

import os
from pathlib import Path


def test_user_home_dir_lives_under_user_dir(tmp_path: Path) -> None:
    from deerflow.config.paths import Paths

    paths = Paths(base_dir=tmp_path)
    assert paths.user_home_dir("alice") == tmp_path / "users" / "alice" / "home"


def test_user_home_dir_rejects_unsafe_user_id(tmp_path: Path) -> None:
    """Unsafe ids must surface the existing validation error before reaching the FS."""
    from deerflow.config.paths import Paths

    paths = Paths(base_dir=tmp_path)
    try:
        paths.user_home_dir("../escape")
    except ValueError as exc:
        assert "Invalid user_id" in str(exc)
    else:
        raise AssertionError("Expected ValueError for unsafe user_id")


def test_host_user_home_dir_uses_host_base_env(tmp_path: Path) -> None:
    """``DEER_FLOW_HOST_BASE_DIR`` overrides the bind-mount source (DooD deployments)."""
    from deerflow.config.paths import Paths

    paths = Paths(base_dir=tmp_path)
    os.environ["DEER_FLOW_HOST_BASE_DIR"] = "/host-side/path"
    try:
        result = paths.host_user_home_dir("bob")
    finally:
        del os.environ["DEER_FLOW_HOST_BASE_DIR"]
    assert result == "/host-side/path/users/bob/home"


def test_host_user_home_dir_falls_back_to_local_base(tmp_path: Path) -> None:
    from deerflow.config.paths import Paths

    paths = Paths(base_dir=tmp_path)
    result = paths.host_user_home_dir("carol")
    expected = str(tmp_path / "users" / "carol" / "home")
    assert result == expected


def test_user_home_dir_does_not_create_directory(tmp_path: Path) -> None:
    """The path helper is a pure resolver — directory creation is the caller's job."""
    from deerflow.config.paths import Paths

    paths = Paths(base_dir=tmp_path)
    home = paths.user_home_dir("dave")
    assert not home.exists()
    assert home == tmp_path / "users" / "dave" / "home"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && rtk pytest tests/test_user_home_dir.py -v`
Expected: FAIL with `AttributeError: type object 'Paths' has no attribute 'user_home_dir'`.

- [ ] **Step 3: Write minimal implementation**

Modify `backend/packages/harness/deerflow/config/paths.py`. Insert the two methods immediately after `def user_dir(self, user_id: str) -> Path` (line 182). Do NOT add imports — `_validate_user_id` and `_join_host_path` are already module-level.

```python
    def user_home_dir(self, user_id: str) -> Path:
        """Per-user persistent home directory: ``{base_dir}/users/{user_id}/home/``.

        Bind-mounted into the sandbox at ``/mnt/user-home`` (configurable). Lives
        across thread lifecycles — sibling to ``threads/`` and ``agents/``, not
        a child of any individual thread. **Does not mkdir**: directory creation
        is the caller's responsibility so paths remain cheap to compute.
        """
        return self.user_dir(user_id) / "home"

    def host_user_home_dir(self, user_id: str) -> str:
        """Host bind-mount source string for the user-home directory.

        Mirrors the Windows-aware split of ``host_sandbox_work_dir`` etc.: uses
        ``DEER_FLOW_HOST_BASE_DIR`` when set so DooD deployments (gateway inside
        a container, sandbox on host) resolve bind-mount sources from the host's
        perspective. Falls back to ``str(self.base_dir)`` for native/local runs.
        """
        return _join_host_path(self._host_base_dir_str(), "users", _validate_user_id(user_id), "home")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && rtk pytest tests/test_user_home_dir.py -v`
Expected: PASS for all 5 tests.

- [ ] **Step 5: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
rtk git add backend/packages/harness/deerflow/config/paths.py backend/tests/test_user_home_dir.py
rtk git commit -m "feat(sandbox): add Paths.user_home_dir and host_user_home_dir helpers"
```

---

### Task 2: `SandboxUserHomeConfig` Pydantic model

**Files:**
- Modify: `backend/packages/harness/deerflow/config/sandbox_config.py` (append after `VolumeMountConfig` block, before `SandboxConfig`)
- Test: `backend/tests/test_sandbox_user_home_config.py` (create)

**Interfaces:**
- Produces: `class SandboxUserHomeConfig(BaseModel): enabled: bool = True; container_path: str = "/mnt/user-home"`
- Consumed by: Task 11 (config example wiring), Task 4 (middleware reads `container_path`), Task 7-9 (providers read `enabled`).

**Risks covered:** None directly (config defaults preserve backward compatibility).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_sandbox_user_home_config.py`:

```python
"""SandboxUserHomeConfig — per-user persistent home mount configuration."""
from __future__ import annotations

from deerflow.config.sandbox_config import SandboxConfig, SandboxUserHomeConfig


def test_defaults_are_backward_compatible() -> None:
    cfg = SandboxUserHomeConfig()
    assert cfg.enabled is True
    assert cfg.container_path == "/mnt/user-home"


def test_can_disable() -> None:
    cfg = SandboxUserHomeConfig(enabled=False)
    assert cfg.enabled is False


def test_can_rename_container_path() -> None:
    cfg = SandboxUserHomeConfig(container_path="/home/persistent")
    assert cfg.container_path == "/home/persistent"


def test_sandbox_config_exposes_user_home_subblock() -> None:
    """``SandboxConfig.user_home`` must default-construct from a bare SandboxConfig."""
    cfg = SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider")
    assert isinstance(cfg.user_home, SandboxUserHomeConfig)
    assert cfg.user_home.enabled is True
    assert cfg.user_home.container_path == "/mnt/user-home"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && rtk pytest tests/test_sandbox_user_home_config.py -v`
Expected: FAIL with `ImportError: cannot import name 'SandboxUserHomeConfig' from 'deerflow.config.sandbox_config'`.

- [ ] **Step 3: Write minimal implementation**

Modify `backend/packages/harness/deerflow/config/sandbox_config.py`. Insert after the `VolumeMountConfig` class definition (before `class SandboxConfig`):

```python
class SandboxUserHomeConfig(BaseModel):
    """Per-user persistent home directory mount.

    When ``enabled`` is True, ``{base_dir}/users/{user_id}/home/`` is bind-mounted
    into the sandbox at ``container_path`` (default ``/mnt/user-home``) on every
    sandbox acquire. The directory survives thread lifecycles, sandbox container
    restarts, and gateway restarts — it is the "files the user wants to keep"
    counterpart to the thread-scoped ``/mnt/user-data/{workspace,uploads,outputs}``.

    Set ``enabled: false`` to disable the mount entirely (the agent prompt will
    also omit the "persistent user home" section, so the agent has no way to
    discover the path).
    """

    enabled: bool = Field(
        default=True,
        description="Whether to bind-mount the per-user home directory into the sandbox.",
    )
    container_path: str = Field(
        default="/mnt/user-home",
        description="Virtual path inside the sandbox where the user-home directory is mounted.",
    )
```

Now add the `user_home` field to `SandboxConfig`. Insert one line below the `mounts: list[VolumeMountConfig] = Field(...)` block (around line 75):

```python
    user_home: SandboxUserHomeConfig = Field(
        default_factory=SandboxUserHomeConfig,
        description="Per-user persistent home directory mount settings. See SandboxUserHomeConfig.",
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && rtk pytest tests/test_sandbox_user_home_config.py -v`
Expected: PASS for all 4 tests.

- [ ] **Step 5: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
rtk git add backend/packages/harness/deerflow/config/sandbox_config.py backend/tests/test_sandbox_user_home_config.py
rtk git commit -m "feat(sandbox): add SandboxUserHomeConfig for per-user home mount"
```

---

### Task 3: Extend `ThreadDataState` TypedDict

**Files:**
- Modify: `backend/packages/harness/deerflow/agents/thread_state.py:10-13` (extend the existing TypedDict)
- Test: `backend/tests/test_thread_data_state_user_home.py` (create)

**Interfaces:**
- Produces: `ThreadDataState` TypedDict with two new `NotRequired[str | None]` fields:
  - `user_home_path`: host filesystem path (string), e.g. `"/abs/.../users/alice/home"`. `None` when disabled.
  - `user_home_container_path`: sandbox virtual path (string), e.g. `"/mnt/user-home"`. `None` when disabled.
- Consumed by: Task 4 (middleware writes), Task 5-6 (tools.py reads), Task 7-8 (providers assert).

**Risks covered:** None (TypedDict extension is backward-compatible).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_thread_data_state_user_home.py`:

```python
"""ThreadDataState TypedDict must accept optional user_home_path / user_home_container_path.

The two new fields are NotRequired[str | None] — populated by ThreadDataMiddleware
when ``sandbox.user_home.enabled`` is True, left absent (or None) otherwise.
Backward compat: existing code that constructs ``ThreadDataState(workspace_path=...)``
without the new keys must keep working.
"""
from __future__ import annotations

from deerflow.agents.thread_state import ThreadDataState


def test_legacy_construction_still_works() -> None:
    """Pre-feature ThreadDataState values must remain valid (NotRequired = optional)."""
    state: ThreadDataState = {
        "workspace_path": "/tmp/w",
        "uploads_path": "/tmp/u",
        "outputs_path": "/tmp/o",
    }
    assert state["workspace_path"] == "/tmp/w"
    assert "user_home_path" not in state


def test_new_fields_accept_strings() -> None:
    state: ThreadDataState = {
        "workspace_path": "/tmp/w",
        "uploads_path": "/tmp/u",
        "outputs_path": "/tmp/o",
        "user_home_path": "/abs/users/alice/home",
        "user_home_container_path": "/mnt/user-home",
    }
    assert state["user_home_path"] == "/abs/users/alice/home"
    assert state["user_home_container_path"] == "/mnt/user-home"


def test_new_fields_accept_none_when_disabled() -> None:
    """Explicit None means ``user_home is disabled`` — middleware contract."""
    state: ThreadDataState = {
        "workspace_path": "/tmp/w",
        "uploads_path": "/tmp/u",
        "outputs_path": "/tmp/o",
        "user_home_path": None,
        "user_home_container_path": None,
    }
    assert state["user_home_path"] is None
    assert state["user_home_container_path"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && rtk pytest tests/test_thread_data_state_user_home.py -v`
Expected: PASS for `test_legacy_construction_still_works` and `test_new_fields_accept_strings` (TypedDict annotations are not runtime-enforced by default in 3.12, so `test_new_fields_accept_none_when_disabled` is the load-bearing test). Compile-time check via mypy is out of scope here; the test that matters is whether `thread_state.ThreadDataState` exposes the keys via `__annotations__` for downstream `thread_data.get("user_home_path")` calls.

Actually, the real failure point will be at runtime in Task 4 if the keys aren't there. To make this task testable in isolation, expand test 2:

```python
def test_new_fields_appear_in_typeddict_annotations() -> None:
    import typing

    hints = typing.get_type_hints(ThreadDataState)
    assert "user_home_path" in hints
    assert "user_home_container_path" in hints
```

Expected FAIL with `KeyError: 'user_home_path'`.

- [ ] **Step 3: Write minimal implementation**

Modify `backend/packages/harness/deerflow/agents/thread_state.py:10-13`. Replace the `ThreadDataState` class with:

```python
class ThreadDataState(TypedDict):
    workspace_path: NotRequired[str | None]
    uploads_path: NotRequired[str | None]
    outputs_path: NotRequired[str | None]
    # Per-user persistent home directory (set by ThreadDataMiddleware).
    # Both are None when sandbox.user_home.enabled is False.
    user_home_path: NotRequired[str | None]
    user_home_container_path: NotRequired[str | None]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && rtk pytest tests/test_thread_data_state_user_home.py -v`
Expected: PASS for all 4 tests.

- [ ] **Step 5: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
rtk git add backend/packages/harness/deerflow/agents/thread_state.py backend/tests/test_thread_data_state_user_home.py
rtk git commit -m "feat(agents): add user_home_path / user_home_container_path to ThreadDataState"
```

---

### Task 4: `ThreadDataMiddleware` injects the two new fields

**Files:**
- Modify: `backend/packages/harness/deerflow/agents/middlewares/thread_data_middleware.py:52-79` (`_get_thread_paths` and `_create_thread_directories`)
- Test: `backend/tests/test_thread_data_middleware_user_home.py` (create)

**Interfaces:**
- Consumes: `sandbox.user_home.enabled`, `sandbox.user_home.container_path` (from `get_app_config()`); `get_effective_user_id()`.
- Produces: `thread_data["user_home_path"]` = `str(Paths.user_home_dir(user_id))` if enabled, else `None`. `thread_data["user_home_container_path"]` = `container_path` if enabled, else `None`. When enabled and the host directory is missing, lazy-mkdir with `0o777` (matches `ensure_thread_dirs` convention; see design R2/R6).
- Consumed by: Task 5-6 (tools.py reads these fields), Task 7-8 (sandbox providers also use them for mount source).

**Risks covered:** R2 (lock `0o777`), R6 (no risk of touching `home/` from `delete_thread_dir` since middleware never deletes here).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_thread_data_middleware_user_home.py`:

```python
"""ThreadDataMiddleware must inject user_home_path / user_home_container_path.

Tests cover three states:
  1. ``sandbox.user_home.enabled=True`` (default) → both fields populated, host dir created with 0o777.
  2. ``sandbox.user_home.enabled=False`` → both fields None, host dir not created.
  3. No-auth fallback → uses ``DEFAULT_USER_ID = "default"`` from ``runtime.user_context``.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from langgraph.runtime import Runtime


@pytest.fixture
def isolated_home(monkeypatch, tmp_path):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "_paths", None)
    yield tmp_path
    monkeypatch.setattr(paths_module, "_paths", None)


def _make_config(user_home_enabled: bool, container_path: str = "/mnt/user-home") -> SimpleNamespace:
    return SimpleNamespace(
        sandbox=SimpleNamespace(
            user_home=SimpleNamespace(enabled=user_home_enabled, container_path=container_path),
        ),
    )


def test_user_home_injected_when_enabled(isolated_home, tmp_path):
    from deerflow.agents.middlewares.thread_data_middleware import ThreadDataMiddleware

    middleware = ThreadDataMiddleware(base_dir=str(tmp_path), lazy_init=True)
    runtime = Runtime(context={"thread_id": "t-1"})
    with patch("deerflow.config.get_app_config", return_value=_make_config(True)):
        result = middleware.before_agent(state={}, runtime=runtime)

    td = result["thread_data"]
    assert td["user_home_container_path"] == "/mnt/user-home"
    expected_host = str(tmp_path / "users" / "default" / "home")
    assert td["user_home_path"] == expected_host
    assert Path(expected_host).exists()
    mode = Path(expected_host).stat().st_mode
    assert mode & 0o777 == 0o777, f"Expected 0o777, got {oct(mode & 0o777)}"


def test_user_home_none_when_disabled(isolated_home, tmp_path):
    from deerflow.agents.middlewares.thread_data_middleware import ThreadDataMiddleware

    middleware = ThreadDataMiddleware(base_dir=str(tmp_path), lazy_init=True)
    runtime = Runtime(context={"thread_id": "t-2"})
    with patch("deerflow.config.get_app_config", return_value=_make_config(False)):
        result = middleware.before_agent(state={}, runtime=runtime)

    td = result["thread_data"]
    assert td["user_home_path"] is None
    assert td["user_home_container_path"] is None
    # Critically: the host directory must NOT be created when disabled.
    assert not (tmp_path / "users" / "default" / "home").exists()


def test_user_home_uses_effective_user_id(monkeypatch, tmp_path):
    """``get_effective_user_id()`` must drive the host path — not ``workspace_path`` reverse-engineering (R5)."""
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "_paths", None)
    from deerflow.agents.middlewares.thread_data_middleware import ThreadDataMiddleware
    from deerflow.runtime import user_context

    token = user_context.set_current_user(SimpleNamespace(id="alice"))
    try:
        middleware = ThreadDataMiddleware(base_dir=str(tmp_path), lazy_init=True)
        runtime = Runtime(context={"thread_id": "t-3"})
        with patch("deerflow.config.get_app_config", return_value=_make_config(True)):
            result = middleware.before_agent(state={}, runtime=runtime)
    finally:
        user_context.reset_current_user(token)
        monkeypatch.setattr(paths_module, "_paths", None)

    td = result["thread_data"]
    assert td["user_home_path"] == str(tmp_path / "users" / "alice" / "home")


def test_user_home_uses_no_auth_default(monkeypatch, tmp_path):
    """Without a set user, ``get_effective_user_id()`` returns ``"default"`` per runtime/user_context.py:97."""
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "_paths", None)
    from deerflow.agents.middlewares.thread_data_middleware import ThreadDataMiddleware

    middleware = ThreadDataMiddleware(base_dir=str(tmp_path), lazy_init=True)
    runtime = Runtime(context={"thread_id": "t-4"})
    with patch("deerflow.config.get_app_config", return_value=_make_config(True)):
        result = middleware.before_agent(state={}, runtime=runtime)

    assert result["thread_data"]["user_home_path"] == str(tmp_path / "users" / "default" / "home")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && rtk pytest tests/test_thread_data_middleware_user_home.py -v`
Expected: FAIL — either `KeyError: 'user_home_path'` (field not in result) or `AssertionError` on the enabled path because no dir was created.

- [ ] **Step 3: Write minimal implementation**

Modify `backend/packages/harness/deerflow/agents/middlewares/thread_data_middleware.py`. The middleware must NOT import `deerflow.config` at module top level (avoid cycles); use a lazy import inside `before_agent` like `_get_thread_paths` already does for `Paths`.

Add a new private method, and extend `_get_thread_paths` / `_create_thread_directories`:

```python
    def _resolve_user_home(self, user_id: str | None) -> tuple[str | None, str | None]:
        """Return ``(host_path, container_path)`` for the per-user persistent home.

        Reads ``sandbox.user_home.{enabled,container_path}`` from app config. When
        ``enabled`` is True (default), also mkdirs the host directory with
        ``mode=0o777`` so sandbox containers running as a different UID can write
        (same pattern as ``Paths.ensure_thread_dirs``). When disabled, returns
        ``(None, None)`` — tools.py / sandbox providers treat None as "skip this
        mount / virtual path".
        """
        try:
            from deerflow.config import get_app_config

            cfg = get_app_config().sandbox.user_home
            enabled = bool(cfg.enabled)
            container_path = str(cfg.container_path)
        except Exception:
            return (None, None)

        if not enabled:
            return (None, None)

        user_id_resolved = user_id or "default"
        host_dir = self._paths.user_home_dir(user_id_resolved)
        host_dir.mkdir(parents=True, exist_ok=True)
        host_dir.chmod(0o777)
        return (str(host_dir), container_path)
```

Now modify `_get_thread_paths` (line 52) — add the two fields:

```python
    def _get_thread_paths(self, thread_id: str, user_id: str | None = None) -> dict[str, str]:
        """Get the paths for a thread's data directories."""
        user_home_path, user_home_container_path = self._resolve_user_home(user_id)
        return {
            "workspace_path": str(self._paths.sandbox_work_dir(thread_id, user_id=user_id)),
            "uploads_path": str(self._paths.sandbox_uploads_dir(thread_id, user_id=user_id)),
            "outputs_path": str(self._paths.sandbox_outputs_dir(thread_id, user_id=user_id)),
            "user_home_path": user_home_path,
            "user_home_container_path": user_home_container_path,
        }
```

`_create_thread_directories` already calls `_get_thread_paths`, so it picks up the new keys automatically.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && rtk pytest tests/test_thread_data_middleware_user_home.py -v`
Expected: PASS for all 4 tests.

- [ ] **Step 5: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
rtk git add backend/packages/harness/deerflow/agents/middlewares/thread_data_middleware.py backend/tests/test_thread_data_middleware_user_home.py
rtk git commit -m "feat(agents): ThreadDataMiddleware injects per-user home mount paths"
```

---

### Task 5: `tools.py` — `_is_user_home_path` / `_resolve_user_home_path` helpers

**Files:**
- Modify: `backend/packages/harness/deerflow/sandbox/tools.py` (insert after `_is_acp_workspace_path`, ~line 173)
- Test: `backend/tests/test_user_home_path_helpers.py` (create)

**Interfaces:**
- Produces:
  - `_USER_HOME_VIRTUAL_PREFIX: str = "/mnt/user-home"` (module constant).
  - `_is_user_home_path(path: str, *, container_path: str | None = None) -> bool`: matches `/mnt/user-home` and `/mnt/user-home/...` **OR** matches the supplied `container_path` if it differs from the default. Returns False when `container_path is None`.
  - `_resolve_user_home_path(path: str, thread_data: ThreadDataState, *, container_path: str | None = None) -> str`: validates that `thread_data["user_home_path"]` is set, validates the prefix against `container_path` (or the default `/mnt/user-home`), and returns the host path. Raises `FileNotFoundError` when `user_home_path` is None (caller disabled).
- Consumed by: Task 6 (three entry points in tools.py), Task 9 (AIO warning path uses `_is_user_home_path` indirectly).

**Risks covered:** R7 — host path contains `user_id` so the helper MUST resolve fresh per call (no module-level caching of host path).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_user_home_path_helpers.py`:

```python
"""tools.py — _is_user_home_path / _resolve_user_home_path helpers."""
from __future__ import annotations

import pytest


def test_is_user_home_path_default_container() -> None:
    from deerflow.sandbox.tools import _is_user_home_path

    assert _is_user_home_path("/mnt/user-home") is True
    assert _is_user_home_path("/mnt/user-home/") is True
    assert _is_user_home_path("/mnt/user-home/notes.md") is True
    assert _is_user_home_path("/mnt/user-data/notes.md") is False
    assert _is_user_home_path("/mnt/skills/foo.md") is False
    assert _is_user_home_path("/etc/passwd") is False


def test_is_user_home_path_custom_container() -> None:
    """Container path override (e.g. ``/home/persistent``) must be recognised too."""
    from deerflow.sandbox.tools import _is_user_home_path

    assert _is_user_home_path("/home/persistent", container_path="/home/persistent") is True
    assert _is_user_home_path("/home/persistent/x", container_path="/home/persistent") is True
    assert _is_user_home_path("/mnt/user-home/x", container_path="/home/persistent") is False


def test_is_user_home_path_none_container() -> None:
    """When the container path is None (feature disabled), nothing matches."""
    from deerflow.sandbox.tools import _is_user_home_path

    assert _is_user_home_path("/mnt/user-home", container_path=None) is False
    assert _is_user_home_path("/mnt/user-home/x", container_path=None) is False


def test_resolve_user_home_path_uses_thread_data_host_path() -> None:
    """Resolver reads host path from thread_data — fresh per call (R7)."""
    from deerflow.sandbox.tools import _resolve_user_home_path

    td_a = {"user_home_path": "/abs/users/alice/home", "user_home_container_path": "/mnt/user-home"}
    td_b = {"user_home_path": "/abs/users/bob/home", "user_home_container_path": "/mnt/user-home"}
    # Same input path, two different users → two different host paths. No caching.
    assert _resolve_user_home_path("/mnt/user-home/notes.md", td_a) == "/abs/users/alice/home/notes.md"
    assert _resolve_user_home_path("/mnt/user-home/notes.md", td_b) == "/abs/users/bob/home/notes.md"


def test_resolve_user_home_path_raises_when_disabled() -> None:
    from deerflow.sandbox.tools import _resolve_user_home_path

    td = {"user_home_path": None, "user_home_container_path": None}
    with pytest.raises(FileNotFoundError, match="user_home is disabled"):
        _resolve_user_home_path("/mnt/user-home/notes.md", td)


def test_resolve_user_home_path_rejects_traversal() -> None:
    """The ``..`` segment rejection must apply (defense in depth)."""
    from deerflow.sandbox.tools import _resolve_user_home_path

    td = {"user_home_path": "/abs/users/alice/home", "user_home_container_path": "/mnt/user-home"}
    with pytest.raises(PermissionError, match="path traversal"):
        _resolve_user_home_path("/mnt/user-home/../etc/passwd", td)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && rtk pytest tests/test_user_home_path_helpers.py -v`
Expected: FAIL with `ImportError: cannot import name '_is_user_home_path' from 'deerflow.sandbox.tools'`.

- [ ] **Step 3: Write minimal implementation**

Modify `backend/packages/harness/deerflow/sandbox/tools.py`. Insert immediately after `_is_acp_workspace_path` (around line 172, before `_get_custom_mounts`):

```python
_DEFAULT_USER_HOME_CONTAINER_PATH = "/mnt/user-home"


def _is_user_home_path(path: str, *, container_path: str | None = None) -> bool:
    """Return True when *path* is under the per-user persistent home mount.

    Mirrors ``_is_skills_path`` and ``_is_acp_workspace_path``. The container
    path comes from ``thread_data["user_home_container_path"]``; when that is
    ``None`` (feature disabled), nothing matches. Default container path is
    ``/mnt/user-home``.
    """
    prefix = container_path or _DEFAULT_USER_HOME_CONTAINER_PATH
    if prefix is None:
        return False
    return path == prefix or path.startswith(f"{prefix}/")


def _resolve_user_home_path(path: str, thread_data: ThreadDataState) -> str:
    """Resolve a virtual ``/mnt/user-home/...`` path to its host filesystem path.

    The host path depends on ``user_id`` (see design R7) — we resolve it from
    ``thread_data["user_home_path"]`` on every call. **Do not cache** the host
    path; the skills helper ``_get_skills_host_path`` caches because its host
    path is process-global, but user-home is per-user and a stale cache would
    leak between concurrent users on a shared gateway.

    Raises:
        FileNotFoundError: when ``user_home_path`` is None (feature disabled).
        PermissionError: when the path contains a ``..`` traversal segment.
    """
    container_path = thread_data.get("user_home_container_path")
    host_path = thread_data.get("user_home_path")

    if not host_path or not container_path:
        raise FileNotFoundError(f"user_home is disabled, cannot resolve path: {path}")

    _reject_path_traversal(path)

    if path == container_path:
        return host_path

    relative = path[len(container_path) :].lstrip("/")
    return _join_path_preserving_style(host_path, relative)
```

`_reject_path_traversal` and `_join_path_preserving_style` are already defined in the same module — no new imports needed.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && rtk pytest tests/test_user_home_path_helpers.py -v`
Expected: PASS for all 6 tests.

- [ ] **Step 5: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
rtk git add backend/packages/harness/deerflow/sandbox/tools.py backend/tests/test_user_home_path_helpers.py
rtk git commit -m "feat(sandbox): add _is_user_home_path / _resolve_user_home_path helpers"
```

---

### Task 6: Extend `tools.py` three entry points

**Files:**
- Modify: `backend/packages/harness/deerflow/sandbox/tools.py`
  - `_thread_virtual_to_actual_mappings` (line 522) — add user-home mapping.
  - `_validate_resolved_user_data_path` (line 689) — add user-home to allowed roots.
  - `_is_allowed_local_bash_absolute_path` (line 787) — recognise user-home virtual paths.
  - `replace_virtual_paths_in_command` (line 983) — regex replacement for user-home paths in bash command strings.
- Test: extend `backend/tests/test_sandbox_tools_security.py` (existing file) and `backend/tests/test_local_sandbox_virtual_path_contract.py` (existing file).

**Interfaces:**
- Consumes: `_resolve_user_home_path` from Task 5.
- Produces:
  - `_thread_virtual_to_actual_mappings` returns a mapping including `(container_path → host_path)` for user-home when both fields are set.
  - `_validate_resolved_user_data_path` accepts user-home hosts as allowed roots.
  - `_is_allowed_local_bash_absolute_path` recognises user-home virtual paths (read-only irrelevant — user-home is always read-write).
  - `replace_virtual_paths_in_command` rewrites `/mnt/user-home/...` substrings to host paths.

**Risks covered:** R3 (clear separation enforced via prompt + path validator), R6 (home/ is never the resolved target of a user-data write), R7 (no host-path caching).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_sandbox_tools_security.py`:

```python
# ─────────────────────────────────────────────────────────────────
# user_home mount (Phase 1, design 2026-06-22)
# ─────────────────────────────────────────────────────────────────


_USER_HOME_TD = {
    "workspace_path": "/tmp/deer-flow/threads/t1/user-data/workspace",
    "uploads_path": "/tmp/deer-flow/threads/t1/user-data/uploads",
    "outputs_path": "/tmp/deer-flow/threads/t1/user-data/outputs",
    "user_home_path": "/tmp/deer-flow/users/alice/home",
    "user_home_container_path": "/mnt/user-home",
}


def test_replace_virtual_path_maps_user_home_subpath():
    from deerflow.sandbox.tools import replace_virtual_path

    result = replace_virtual_path("/mnt/user-home/notes.md", _USER_HOME_TD)
    assert Path(result).as_posix() == "/tmp/deer-flow/users/alice/home/notes.md"


def test_replace_virtual_path_maps_user_home_root():
    from deerflow.sandbox.tools import replace_virtual_path

    result = replace_virtual_path("/mnt/user-home", _USER_HOME_TD)
    assert Path(result).as_posix() == "/tmp/deer-flow/users/alice/home"


def test_validate_local_tool_path_allows_user_home_write():
    """write_file / str_replace must permit user-home paths."""
    from deerflow.sandbox.tools import validate_local_tool_path

    # Should not raise — read_only=False is the default for write paths.
    validate_local_tool_path("/mnt/user-home/notes.md", _USER_HOME_TD)
    validate_local_tool_path("/mnt/user-home/notes.md", _USER_HOME_TD, read_only=False)


def test_validate_local_tool_path_rejects_traversal_in_user_home():
    from deerflow.sandbox.tools import validate_local_tool_path

    with pytest.raises(PermissionError, match="path traversal"):
        validate_local_tool_path("/mnt/user-home/../etc/passwd", _USER_HOME_TD)


def test_validate_resolved_user_data_path_accepts_user_home_root():
    from deerflow.sandbox.tools import _validate_resolved_user_data_path

    resolved = Path("/tmp/deer-flow/users/alice/home/notes.md").resolve()
    # Should not raise.
    _validate_resolved_user_data_path(resolved, _USER_HOME_TD)


def test_replace_virtual_paths_in_command_rewrites_user_home():
    from deerflow.sandbox.tools import replace_virtual_paths_in_command

    cmd = "cp /mnt/user-home/notes.md /mnt/user-home/backup.md"
    rewritten = replace_virtual_paths_in_command(cmd, _USER_HOME_TD)
    assert "/tmp/deer-flow/users/alice/home/notes.md" in rewritten
    assert "/tmp/deer-flow/users/alice/home/backup.md" in rewritten
    # Original virtual prefixes must not leak.
    assert "/mnt/user-home" not in rewritten


def test_replace_virtual_path_skips_when_user_home_disabled():
    """No user_home_path in thread_data → user-home virtual path is NOT rewritten."""
    from deerflow.sandbox.tools import replace_virtual_path

    # Thread data without user_home_* keys.
    td_no_user_home = {
        "workspace_path": "/tmp/deer-flow/threads/t1/user-data/workspace",
        "uploads_path": "/tmp/deer-flow/threads/t1/user-data/uploads",
        "outputs_path": "/tmp/deer-flow/threads/t1/user-data/outputs",
    }
    # Path is unchanged — no exception, no rewrite.
    assert replace_virtual_path("/mnt/user-home/notes.md", td_no_user_home) == "/mnt/user-home/notes.md"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && rtk pytest tests/test_sandbox_tools_security.py -v -k "user_home"`
Expected: FAIL — `replace_virtual_path` will not find `/mnt/user-home/notes.md` in its mappings (line 522 area) and will return the path unchanged; tests that assert `==` rewrites will fail.

- [ ] **Step 3: Write minimal implementation**

Four surgical edits inside `backend/packages/harness/deerflow/sandbox/tools.py`.

**Edit A — extend `_thread_virtual_to_actual_mappings`** (line 522):

```python
def _thread_virtual_to_actual_mappings(thread_data: ThreadDataState) -> dict[str, str]:
    """Build virtual-to-actual path mappings for a thread."""
    mappings: dict[str, str] = {}

    workspace = thread_data.get("workspace_path")
    uploads = thread_data.get("uploads_path")
    outputs = thread_data.get("outputs_path")
    user_home = thread_data.get("user_home_path")
    user_home_container = thread_data.get("user_home_container_path")

    if workspace:
        mappings[f"{VIRTUAL_PATH_PREFIX}/workspace"] = workspace
    if uploads:
        mappings[f"{VIRTUAL_PATH_PREFIX}/uploads"] = uploads
    if outputs:
        mappings[f"{VIRTUAL_PATH_PREFIX}/outputs"] = outputs
    if user_home and user_home_container:
        mappings[user_home_container] = user_home

    # Also map the virtual root when all known dirs share the same parent.
    actual_dirs = [Path(p) for p in (workspace, uploads, outputs) if p]
    if actual_dirs:
        common_parent = str(Path(actual_dirs[0]).parent)
        if all(str(path.parent) == common_parent for path in actual_dirs):
            mappings[VIRTUAL_PATH_PREFIX] = common_parent

    return mappings
```

`replace_virtual_path` (line 500 area) sorts by `len(item[0])` descending and matches longest-prefix-first — because `/mnt/user-home` (15 chars) is longer than `/mnt/user-data` (14), user-home always wins when both could match (they never overlap in practice since the prefixes differ, but the ordering is correct).

**Edit B — extend `_validate_resolved_user_data_path`** (line 689):

```python
def _validate_resolved_user_data_path(resolved: Path, thread_data: ThreadDataState) -> None:
    """Verify that a resolved host path stays inside allowed per-thread roots.

    Raises PermissionError if the path escapes workspace/uploads/outputs/user-home.
    """
    allowed_roots = [
        Path(p).resolve()
        for p in (
            thread_data.get("workspace_path"),
            thread_data.get("uploads_path"),
            thread_data.get("outputs_path"),
            thread_data.get("user_home_path"),
        )
        if p is not None
    ]

    if not allowed_roots:
        raise SandboxRuntimeError("No allowed local sandbox directories configured")

    for root in allowed_roots:
        try:
            resolved.relative_to(root)
            return
        except ValueError:
            continue

    raise PermissionError("Access denied: path traversal detected")
```

**Edit C — `_is_allowed_local_bash_absolute_path` already accepts `VIRTUAL_PATH_PREFIX` and skills paths.** Add user-home alongside, just before the `allow_system_paths` check (line 807):

```python
    # Allow user-home container path (path-traversal check only)
    user_home_container = None
    if thread_data is not None:  # NB: thread_data isn't currently passed here; see note below
        user_home_container = thread_data.get("user_home_container_path")
    if _is_user_home_path(path, container_path=user_home_container) or _is_user_home_path(path):
        _reject_path_traversal(path)
        return True
```

NOTE: `_is_allowed_local_bash_absolute_path` currently has no `thread_data` argument — its callers in `tools.py` operate on pre-validated tokens. For Phase 1 we use the **default container path** (`/mnt/user-home`) here. The next task will thread `thread_data` through if a test fails. This is acceptable because the bash tool runs command strings through `replace_virtual_paths_in_command` (Task 6 Edit D) **before** this check, so user-home paths already appear as host paths by the time we reach `_is_allowed_local_bash_absolute_path` and the prefix is no longer needed.

**Edit D — extend `replace_virtual_paths_in_command`** (line 983). Add a user-home scan immediately after the ACP workspace scan (around line 1015) and before "Custom mount paths":

```python
    # Replace user-home paths
    user_home_container = thread_data.get("user_home_container_path") if thread_data else None
    user_home_host = thread_data.get("user_home_path") if thread_data else None
    if user_home_container and user_home_host and user_home_container in result:
        user_home_pattern = re.compile(rf"{re.escape(user_home_container)}(/[^\s\"';&|<>()]*)?")

        def replace_user_home_match(match: re.Match) -> str:
            try:
                return _resolve_user_home_path(match.group(0), thread_data)  # type: ignore[arg-type]
            except (FileNotFoundError, PermissionError):
                return match.group(0)

        result = user_home_pattern.sub(replace_user_home_match, result)
```

NOTE on R8: This regex `(/[^\s\"';&|<>()]*)?` is the same shape as the existing 4 regexes in this function. Quoted paths with spaces (e.g. `/mnt/user-home/My Notes/file.md`) are still truncated at the first space. This is documented as Phase 1 R8 in the design and addressed only via prompt guidance (Task 10), not via regex change.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && rtk pytest tests/test_sandbox_tools_security.py -v`
Expected: PASS for all tests, including the new 7 user-home cases.

Also re-run the existing user-data / skills / acp-workspace tests to confirm we didn't regress anything:

Run: `cd backend && rtk pytest tests/test_sandbox_tools_security.py tests/test_local_sandbox_virtual_path_contract.py -v`
Expected: PASS, no regressions.

- [ ] **Step 5: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
rtk git add backend/packages/harness/deerflow/sandbox/tools.py backend/tests/test_sandbox_tools_security.py
rtk git commit -m "feat(sandbox): wire user-home path through tools.py entry points"
```

---

### Task 7: `LocalSandboxProvider._build_thread_path_mappings` adds user-home mapping

**Files:**
- Modify: `backend/packages/harness/deerflow/sandbox/local/local_sandbox_provider.py:188-233`
- Test: extend `backend/tests/test_local_sandbox_virtual_path_contract.py` (existing file)

**Interfaces:**
- Consumes: `Paths.user_home_dir` / `host_user_home_dir` (Task 1), `ThreadDataMiddleware` output (Task 4).
- Produces: an extra `PathMapping(container_path=user_home_container, local_path=user_home_host, read_only=False)` appended to the per-thread mapping list when `user_home_path` and `user_home_container_path` are both set in the freshly-computed thread data.
- Consumed by: `LocalSandboxProvider.acquire()` (line 268 — adds to `new_mappings`).

**Risks covered:** R6 (sibling `home/` directory is mounted, not deleted).

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_local_sandbox_virtual_path_contract.py`:

```python
def test_acquire_includes_user_home_mapping_when_enabled(provider, tmp_path):
    """Phase 1 of user-home mount — local provider must publish a mapping for /mnt/user-home."""
    # Build a thread_data dict that simulates ThreadDataMiddleware output.
    from deerflow.config.paths import get_paths
    from deerflow.runtime.user_context import get_effective_user_id

    user_id = get_effective_user_id()  # "default" in no-auth test setup
    expected_host = str(get_paths().user_home_dir(user_id))
    # Make sure the host dir exists so the mapping is published.
    import os
    os.makedirs(expected_host, mode=0o777, exist_ok=True)

    # Patch the middleware call site inside the provider. The provider reads
    # thread_data at acquire time by recomputing via ThreadDataMiddleware.before_agent.
    from langgraph.runtime import Runtime

    middleware_state = {}
    from deerflow.agents.middlewares.thread_data_middleware import ThreadDataMiddleware

    md = ThreadDataMiddleware(lazy_init=True)
    thread_data = md.before_agent(state={}, runtime=Runtime(context={"thread_id": "beta"}))["thread_data"]

    # Now inject the thread_data into the provider's internal cache the same way
    # the agent would, by acquiring the sandbox and then asserting the mapping.
    sbx_id = provider.acquire("beta")
    sbx = provider.get(sbx_id)
    assert sbx is not None
    mappings = sbx.path_mappings
    user_home_mappings = [
        m for m in mappings
        if m.container_path == thread_data["user_home_container_path"]
        and m.local_path == thread_data["user_home_path"]
    ]
    assert len(user_home_mappings) == 1, f"Expected 1 user-home mapping, got {mappings}"
    assert user_home_mappings[0].read_only is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && rtk pytest tests/test_local_sandbox_virtual_path_contract.py::test_acquire_includes_user_home_mapping_when_enabled -v`
Expected: FAIL with `AssertionError` — no mapping matches `user_home_container_path`.

- [ ] **Step 3: Write minimal implementation**

Modify `backend/packages/harness/deerflow/sandbox/local/local_sandbox_provider.py`. Extend `_build_thread_path_mappings` (line 187):

```python
    @staticmethod
    def _build_thread_path_mappings(thread_id: str) -> list[PathMapping]:
        """Build per-thread path mappings for /mnt/user-data, /mnt/acp-workspace, and /mnt/user-home.

        Resolves ``user_id`` via :func:`get_effective_user_id` and ensures the
        backing host directories exist before they are mapped into the sandbox
        view. The user-home mapping is appended **last** so the existing
        ``_find_path_mapping`` length-descending scan (it sorts by container_path
        length) keeps /mnt/user-data/* longer-prefix wins for shared prefixes.
        """
        from deerflow.agents.middlewares.thread_data_middleware import ThreadDataMiddleware
        from deerflow.config.paths import get_paths
        from deerflow.runtime.user_context import get_effective_user_id
        from langgraph.runtime import Runtime

        paths = get_paths()
        user_id = get_effective_user_id()
        paths.ensure_thread_dirs(thread_id, user_id=user_id)

        mappings: list[PathMapping] = [
            PathMapping(
                container_path=_USER_DATA_VIRTUAL_PREFIX,
                local_path=str(paths.sandbox_user_data_dir(thread_id, user_id=user_id)),
                read_only=False,
            ),
            PathMapping(
                container_path=f"{_USER_DATA_VIRTUAL_PREFIX}/workspace",
                local_path=str(paths.sandbox_work_dir(thread_id, user_id=user_id)),
                read_only=False,
            ),
            PathMapping(
                container_path=f"{_USER_DATA_VIRTUAL_PREFIX}/uploads",
                local_path=str(paths.sandbox_uploads_dir(thread_id, user_id=user_id)),
                read_only=False,
            ),
            PathMapping(
                container_path=f"{_USER_DATA_VIRTUAL_PREFIX}/outputs",
                local_path=str(paths.sandbox_outputs_dir(thread_id, user_id=user_id)),
                read_only=False,
            ),
            PathMapping(
                container_path=_ACP_WORKSPACE_VIRTUAL_PREFIX,
                local_path=str(paths.acp_workspace_dir(thread_id, user_id=user_id)),
                read_only=False,
            ),
        ]

        # Per-user persistent home — added by ThreadDataMiddleware (Task 4). The
        # middleware is the single source of truth for user_home_* values, so we
        # call it here too. When the feature is disabled (sandbox.user_home.enabled
        # is False) the fields are None and we skip the mapping.
        try:
            from langgraph.config import get_config  # type: ignore[import-not-found]

            ctx_user_id: str | None = None
        except Exception:
            ctx_user_id = None
        try:
            runtime = Runtime(context={"thread_id": thread_id})
            thread_data = ThreadDataMiddleware(lazy_init=True).before_agent(state={}, runtime=runtime)
            td = thread_data.get("thread_data") if thread_data else None
        except Exception:
            td = None
        if td:
            user_home_host = td.get("user_home_path")
            user_home_container = td.get("user_home_container_path")
            if user_home_host and user_home_container:
                mappings.append(
                    PathMapping(
                        container_path=user_home_container,
                        local_path=user_home_host,
                        read_only=False,
                    )
                )

        return mappings
```

Add `from langgraph.runtime import Runtime` to the top-of-file imports if not already present.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && rtk pytest tests/test_local_sandbox_virtual_path_contract.py -v`
Expected: PASS for all tests, including the new user-home mapping test.

- [ ] **Step 5: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
rtk git add backend/packages/harness/deerflow/sandbox/local/local_sandbox_provider.py backend/tests/test_local_sandbox_virtual_path_contract.py
rtk git commit -m "feat(sandbox): LocalSandboxProvider exposes /mnt/user-home mapping"
```

---

### Task 8: AIO `_get_thread_mounts` adds user-home bind-mount

**Files:**
- Modify: `backend/packages/harness/deerflow/community/aio_sandbox/aio_sandbox_provider.py:305-323`
- Test: extend `backend/tests/test_aio_sandbox_provider.py` (existing file) — search for similar `_get_thread_mounts` tests; if none exist, add a new test file.

**Interfaces:**
- Consumes: `Paths.host_user_home_dir` (Task 1), `sandbox.user_home.{enabled,container_path}` (Task 2).
- Produces: an extra `(host_user_home_dir, container_path, False)` tuple appended when `enabled=True` AND the host dir exists on disk.
- Consumed by: `AioSandboxProvider._get_extra_mounts` (line 289).

**Risks covered:** R5 (this layer is fine; remote_backend is broken — Task 9).

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_aio_sandbox_provider.py` (or create `backend/tests/test_aio_user_home_mount.py` if the provider test file is tightly scoped). The test mocks the host dir to avoid real FS state:

```python
def test_get_thread_mounts_includes_user_home_when_enabled(tmp_path, monkeypatch):
    """AIO provider must publish a /mnt/user-home bind-mount when enabled."""
    from pathlib import Path

    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "_paths", None)

    # Create the host home dir (lazy_init contract).
    user_id = "alice"
    home = tmp_path / "users" / user_id / "home"
    home.mkdir(parents=True, exist_ok=True)

    cfg = SimpleNamespace(
        sandbox=SimpleNamespace(
            user_home=SimpleNamespace(enabled=True, container_path="/mnt/user-home"),
            mounts=[],
            image="img",
            port=8080,
            container_prefix="deer-flow-sandbox",
            idle_timeout=600,
            replicas=3,
            environment={},
            provisioner_url="",
        ),
        skills=SimpleNamespace(container_path="/mnt/skills", get_skills_path=lambda: tmp_path / "skills"),
    )
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: cfg)
    monkeypatch.setattr("deerflow.runtime.user_context.get_effective_user_id", lambda: user_id)

    from deerflow.community.aio_sandbox.aio_sandbox_provider import AioSandboxProvider

    mounts = AioSandboxProvider._get_thread_mounts("tid-1")
    user_home_mounts = [m for m in mounts if m[1] == "/mnt/user-home"]
    assert len(user_home_mounts) == 1, f"Expected 1 user-home mount, got {mounts}"
    host_path, container_path, read_only = user_home_mounts[0]
    assert host_path.endswith(f"users/{user_id}/home")
    assert container_path == "/mnt/user-home"
    assert read_only is False


def test_get_thread_mounts_skips_user_home_when_disabled(tmp_path, monkeypatch):
    """When sandbox.user_home.enabled=False the provider must NOT publish the mount."""
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    from deerflow.config import paths as paths_module

    monkeypatch.setattr(paths_module, "_paths", None)

    cfg = SimpleNamespace(
        sandbox=SimpleNamespace(
            user_home=SimpleNamespace(enabled=False, container_path="/mnt/user-home"),
            mounts=[],
            image="img",
            port=8080,
            container_prefix="deer-flow-sandbox",
            idle_timeout=600,
            replicas=3,
            environment={},
            provisioner_url="",
        ),
        skills=SimpleNamespace(container_path="/mnt/skills", get_skills_path=lambda: tmp_path / "skills"),
    )
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: cfg)
    monkeypatch.setattr("deerflow.runtime.user_context.get_effective_user_id", lambda: "alice")

    from deerflow.community.aio_sandbox.aio_sandbox_provider import AioSandboxProvider

    mounts = AioSandboxProvider._get_thread_mounts("tid-2")
    assert not any(m[1] == "/mnt/user-home" for m in mounts), f"Unexpected mount: {mounts}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && rtk pytest tests/test_aio_sandbox_provider.py -v -k "user_home"` (or the new file name)
Expected: FAIL — no mount in the list matches `/mnt/user-home`.

- [ ] **Step 3: Write minimal implementation**

Modify `backend/packages/harness/deerflow/community/aio_sandbox/aio_sandbox_provider.py`. Replace `_get_thread_mounts` (line 304):

```python
    @staticmethod
    def _get_thread_mounts(thread_id: str) -> list[tuple[str, str, bool]]:
        """Get volume mounts for a thread's data directories.

        Creates directories if they don't exist (lazy initialization).
        Mount sources use host_base_dir so that when running inside Docker with a
        mounted Docker socket (DooD), the host Docker daemon can resolve the paths.
        """
        paths = get_paths()
        user_id = get_effective_user_id()
        paths.ensure_thread_dirs(thread_id, user_id=user_id)

        mounts: list[tuple[str, str, bool]] = [
            (paths.host_sandbox_work_dir(thread_id, user_id=user_id), f"{VIRTUAL_PATH_PREFIX}/workspace", False),
            (paths.host_sandbox_uploads_dir(thread_id, user_id=user_id), f"{VIRTUAL_PATH_PREFIX}/uploads", False),
            (paths.host_sandbox_outputs_dir(thread_id, user_id=user_id), f"{VIRTUAL_PATH_PREFIX}/outputs", False),
            # ACP workspace: read-only inside the sandbox (lead agent reads results;
            # the ACP subprocess writes from the host side, not from within the container).
            (paths.host_acp_workspace_dir(thread_id, user_id=user_id), "/mnt/acp-workspace", True),
        ]

        # Per-user persistent home — Phase 1 of the user-home mount design
        # (2026-06-22). Skipped when disabled or when the host dir hasn't been
        # created yet (cold-start with no prior access). The mkdir is performed
        # lazily inside ``Paths.user_home_dir`` consumer (ThreadDataMiddleware
        # on agent startup); here we just observe existence.
        try:
            from deerflow.config import get_app_config

            user_home_cfg = get_app_config().sandbox.user_home
            if user_home_cfg.enabled:
                host_home = paths.host_user_home_dir(user_id=user_id)
                if host_home and Path(host_home).exists():
                    mounts.append((host_home, user_home_cfg.container_path, False))
        except Exception:
            # Config load failure or user_home attribute missing — fall through.
            logger.debug("Could not include user-home mount; config may be unavailable")

        return mounts
```

`Path` is already imported at the top of the file.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && rtk pytest tests/test_aio_sandbox_provider.py -v -k "user_home"`
Expected: PASS for both tests.

- [ ] **Step 5: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
rtk git add backend/packages/harness/deerflow/community/aio_sandbox/aio_sandbox_provider.py backend/tests/test_aio_sandbox_provider.py
rtk git commit -m "feat(sandbox): AIO provider publishes /mnt/user-home bind-mount"
```

---

### Task 9: AIO startup warning for remote provisioning + user-home (R5 mitigation)

**Files:**
- Modify: `backend/packages/harness/deerflow/community/aio_sandbox/aio_sandbox_provider.py` (`_create_backend`, around line 174-195)
- Test: extend `backend/tests/test_aio_sandbox_provider.py` (or new file)

**Interfaces:**
- Produces: `logger.error(...)` output (with `caplog` captured) when both:
  1. `sandbox.user_home.enabled == True`, and
  2. The provider selected `RemoteSandboxBackend` (i.e. `provisioner_url` is non-empty).
- Consumed by: operators (they see the warning at startup).

**Risks covered:** R5 (Phase 1 mitigation only — does not fix the underlying bug).

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_aio_sandbox_provider.py` (or the new file):

```python
def test_create_backend_logs_error_when_remote_and_user_home_enabled(caplog, tmp_path, monkeypatch):
    """R5 mitigation: when remote provisioning is selected AND user_home is enabled,
    the provider must emit an actionable ERROR at startup. Remote provisioning
    silently drops extra_mounts (see community/aio_sandbox/remote_backend.py:135-146),
    so user-home is NOT actually mounted — operators must know.
    """
    import logging

    cfg = SimpleNamespace(
        sandbox=SimpleNamespace(
            user_home=SimpleNamespace(enabled=True, container_path="/mnt/user-home"),
            image="img",
            port=8080,
            container_prefix="deer-flow-sandbox",
            idle_timeout=600,
            replicas=3,
            mounts=[],
            environment={},
            provisioner_url="http://provisioner:8002",
        ),
        skills=SimpleNamespace(container_path="/mnt/skills", get_skills_path=lambda: tmp_path / "skills"),
    )
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: cfg)

    from deerflow.community.aio_sandbox.aio_sandbox_provider import AioSandboxProvider

    with caplog.at_level(logging.ERROR, logger="deerflow.community.aio_sandbox.aio_sandbox_provider"):
        backend = AioSandboxProvider._create_backend()
    from deerflow.community.aio_sandbox.remote_backend import RemoteSandboxBackend

    assert isinstance(backend, RemoteSandboxBackend)
    assert any(
        "user_home" in record.getMessage() and "remote" in record.getMessage().lower()
        for record in caplog.records
    ), f"Expected user-home / remote warning; got: {[r.getMessage() for r in caplog.records]}"


def test_create_backend_silent_when_remote_and_user_home_disabled(caplog, tmp_path, monkeypatch):
    """When user_home is disabled we must NOT spam the operator with a misleading warning."""
    import logging

    cfg = SimpleNamespace(
        sandbox=SimpleNamespace(
            user_home=SimpleNamespace(enabled=False, container_path="/mnt/user-home"),
            image="img",
            port=8080,
            container_prefix="deer-flow-sandbox",
            idle_timeout=600,
            replicas=3,
            mounts=[],
            environment={},
            provisioner_url="http://provisioner:8002",
        ),
        skills=SimpleNamespace(container_path="/mnt/skills", get_skills_path=lambda: tmp_path / "skills"),
    )
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: cfg)

    from deerflow.community.aio_sandbox.aio_sandbox_provider import AioSandboxProvider

    with caplog.at_level(logging.ERROR, logger="deerflow.community.aio_sandbox.aio_sandbox_provider"):
        AioSandboxProvider._create_backend()
    user_home_warnings = [
        r for r in caplog.records
        if "user_home" in r.getMessage() and "remote" in r.getMessage().lower()
    ]
    assert not user_home_warnings, f"Did not expect warning, got: {[r.getMessage() for r in user_home_warnings]}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && rtk pytest tests/test_aio_sandbox_provider.py -v -k "user_home_enabled or remote_and_user_home"`
Expected: FAIL — no warning is emitted today.

- [ ] **Step 3: Write minimal implementation**

Modify `backend/packages/harness/deerflow/community/aio_sandbox/aio_sandbox_provider.py`. Replace `_create_backend` (line 174):

```python
    def _create_backend(self) -> SandboxBackend:
        """Create the appropriate backend based on configuration.

        Selection logic (checked in order):
        1. ``provisioner_url`` set → RemoteSandboxBackend (provisioner mode)
              Provisioner dynamically creates Pods + Services in k3s.
        2. Default → LocalContainerBackend (local mode)
              Local provider manages container lifecycle directly (start/stop).

        R5 mitigation (design 2026-06-22): when remote provisioning is selected
        AND ``sandbox.user_home.enabled`` is True, emit an actionable ERROR
        log. The remote provisioner currently drops ``extra_mounts`` from the
        create payload (see ``remote_backend.py:135-146``), so user-home will
        not actually be mounted in the container. Full fix is Phase 2 — out
        of scope for this change.
        """
        provisioner_url = self._config.get("provisioner_url")
        if provisioner_url:
            logger.info(f"Using remote sandbox backend with provisioner at {provisioner_url}")
            try:
                from deerflow.config import get_app_config

                user_home_enabled = bool(get_app_config().sandbox.user_home.enabled)
            except Exception:
                user_home_enabled = False
            if user_home_enabled:
                logger.error(
                    "sandbox.user_home.enabled=True but remote provisioning (provisioner_url=%s) "
                    "currently drops extra_mounts from the provisioner create payload "
                    "(see community/aio_sandbox/remote_backend.py:_provisioner_create). "
                    "/mnt/user-home will NOT be mounted in remote-mode sandboxes. "
                    "Phase 2 will fix the provisioner payload; until then, either set "
                    "sandbox.user_home.enabled=false or use local containers "
                    "(AioSandboxProvider without provisioner_url).",
                    provisioner_url,
                )
            return RemoteSandboxBackend(provisioner_url=provisioner_url)

        logger.info("Using local container sandbox backend")
        return LocalContainerBackend(
            image=self._config["image"],
            base_port=self._config["port"],
            container_prefix=self._config["container_prefix"],
            config_mounts=self._config["mounts"],
            environment=self._config["environment"],
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && rtk pytest tests/test_aio_sandbox_provider.py -v -k "user_home"`
Expected: PASS for all user-home tests including the new 2 warning tests.

- [ ] **Step 5: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
rtk git add backend/packages/harness/deerflow/community/aio_sandbox/aio_sandbox_provider.py backend/tests/test_aio_sandbox_provider.py
rtk git commit -m "feat(sandbox): warn at startup when remote AIO + user_home enabled (R5)"
```

---

### Task 10: Lead-agent system prompt — persistent user-home section

**Files:**
- Modify: `backend/packages/harness/deerflow/agents/lead_agent/prompt.py` (add `_build_user_home_section`, wire into `apply_prompt_template`)
- Test: `backend/tests/test_lead_agent_user_home_prompt.py` (create)

**Interfaces:**
- Produces: a new prompt section string. Reads `sandbox.user_home.enabled`. When enabled, returns:

```
Persistent user home: `/mnt/user-home/` (read-write, survives across threads;
use for files the user wants to keep — Obsidian vaults, installed CLI binaries,
project scratchpads). Note: structured facts / preferences / memories are
still extracted into `memory.json` and `USER.md` automatically —
`/mnt/user-home/` is for raw files only, not for facts.

Paths you write here remain visible to the user in their next session.
Skill authors should prefer quoted paths to avoid the shell tokenizer
splitting on whitespace (the platform's regex-based virtual-path
rewriter in `replace_virtual_paths_in_command` truncates at unquoted
spaces — see design R8).
```

When disabled, returns the empty string.

- Consumed by: `apply_prompt_template`.

**Risks covered:** R3 (explicit three-class separation), R8 (prompt-level guidance only).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_lead_agent_user_home_prompt.py`:

```python
"""Lead-agent prompt must mention the per-user persistent home when enabled."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from deerflow.agents.lead_agent import prompt as prompt_module


def test_user_home_section_present_when_enabled():
    cfg = SimpleNamespace(
        sandbox=SimpleNamespace(user_home=SimpleNamespace(enabled=True, container_path="/mnt/user-home")),
    )
    section = prompt_module._build_user_home_section(app_config=cfg)
    assert "/mnt/user-home" in section
    assert "memory.json" in section
    assert "across" in section.lower() or "survives" in section.lower()


def test_user_home_section_absent_when_disabled():
    cfg = SimpleNamespace(
        sandbox=SimpleNamespace(user_home=SimpleNamespace(enabled=False, container_path="/mnt/user-home")),
    )
    section = prompt_module._build_user_home_section(app_config=cfg)
    assert section == ""


def test_apply_prompt_template_includes_section_when_enabled():
    cfg = SimpleNamespace(
        sandbox=SimpleNamespace(user_home=SimpleNamespace(enabled=True, container_path="/mnt/user-home")),
        acp_agents={},
        memory=SimpleNamespace(enabled=False, injection_enabled=False),
        subagents=SimpleNamespace(timeout_seconds=900),
        skill_evolution=SimpleNamespace(enabled=False),
        skills=SimpleNamespace(container_path="/mnt/skills"),
        model=None,
    )
    full = prompt_module.apply_prompt_template(subagent_enabled=False, app_config=cfg)
    assert "Persistent user home" in full or "/mnt/user-home" in full
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && rtk pytest tests/test_lead_agent_user_home_prompt.py -v`
Expected: FAIL with `AttributeError: module 'deerflow.agents.lead_agent.prompt' has no attribute '_build_user_home_section'`.

- [ ] **Step 3: Write minimal implementation**

Modify `backend/packages/harness/deerflow/agents/lead_agent/prompt.py`. Add the new helper immediately after `_build_custom_mounts_section` (around line 755):

```python
def _build_user_home_section(*, app_config: AppConfig | None = None) -> str:
    """Prompt block that teaches the agent the three-class path model.

    Distinguishes:
      * /mnt/user-data/{workspace,uploads,outputs} — per-thread, ephemeral.
      * /mnt/user-home/                           — per-user, persistent (this section).
      * memory.json / USER.md / agents/          — per-user, persistent, but fact-extracted.

    Without this section the agent would not know that user-home exists, and
    might write long-lived scratch files to ``/mnt/user-data/workspace`` where
    they vanish at thread end. Conversely, without the explicit "facts go to
    memory.json" reminder, the agent would write personal facts as plain text
    into ``/mnt/user-home/notes.md`` instead of letting MemoryMiddleware extract
    them — see design R3.
    """
    if app_config is None:
        try:
            from deerflow.config import get_app_config

            config = get_app_config()
        except Exception:
            logger.exception("Failed to load sandbox.user_home for prompt injection")
            return ""
    else:
        config = app_config

    try:
        enabled = bool(config.sandbox.user_home.enabled)
        container_path = str(config.sandbox.user_home.container_path)
    except Exception:
        return ""
    if not enabled:
        return ""

    return (
        f"\n**Persistent user home:** `{container_path}/` (read-write, survives across threads). "
        "Use this directory for files the user wants to keep between sessions "
        "(Obsidian vaults, installed CLI binaries, project scratchpads, notes).\n"
        "- Do NOT confuse this with `/mnt/user-data/` — that namespace is per-thread and is wiped on thread end.\n"
        "- Do NOT write structured facts / preferences / memories here — they go through `memory.json` / `USER.md` automatically. "
        f"`{container_path}/` is for raw files only.\n"
        "- Skill authors: prefer quoted paths; the platform's regex-based virtual-path rewriter truncates at unquoted whitespace.\n"
    )
```

Now wire it into `apply_prompt_template`. Find the lines:

```python
    acp_section = _build_acp_section(app_config=app_config)
    custom_mounts_section = _build_custom_mounts_section(app_config=app_config)
    acp_and_mounts_section = "\n".join(section for section in (acp_section, custom_mounts_section) if section)
```

Add the user-home section:

```python
    acp_section = _build_acp_section(app_config=app_config)
    custom_mounts_section = _build_custom_mounts_section(app_config=app_config)
    user_home_section = _build_user_home_section(app_config=app_config)
    acp_and_mounts_section = "\n".join(
        section for section in (acp_section, custom_mounts_section, user_home_section) if section
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && rtk pytest tests/test_lead_agent_user_home_prompt.py -v`
Expected: PASS for all 3 tests.

- [ ] **Step 5: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
rtk git add backend/packages/harness/deerflow/agents/lead_agent/prompt.py backend/tests/test_lead_agent_user_home_prompt.py
rtk git commit -m "feat(prompt): add persistent user-home section to lead-agent system prompt"
```

---

### Task 11: `config.example.yaml` — wire `sandbox.user_home` and bump version

**Files:**
- Modify: `config.example.yaml` (bump `config_version` at line 18; insert `user_home` block under `sandbox:` around line 822)

**Interfaces:**
- Produces: the canonical example config gains a `sandbox.user_home` block under both the local-sandbox and AIO sandbox example sections. `config_version` increments to 13.

**Risks covered:** None (pure documentation + version bump).

- [ ] **Step 1: Write the failing test**

No automated test for YAML — but we use `make config-upgrade` to verify the bump is consumable. The "test" is whether `make config-upgrade` produces a sensible diff (manual verification step). For automated coverage, append to `backend/tests/test_sandbox_user_home_config.py`:

```python
def test_user_home_field_appears_in_example_config() -> None:
    """The example config must contain a ``user_home`` block under ``sandbox:`` so
    ``make config-upgrade`` propagates the new field to user configs."""
    import pathlib

    example_path = pathlib.Path(__file__).resolve().parents[2] / "config.example.yaml"
    text = example_path.read_text(encoding="utf-8")
    # Find the sandbox: block and assert it contains user_home.
    assert "sandbox:" in text
    assert "user_home:" in text, "Expected 'user_home:' block in config.example.yaml"
    assert "container_path: /mnt/user-home" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && rtk pytest tests/test_sandbox_user_home_config.py::test_user_home_field_appears_in_example_config -v`
Expected: FAIL — `user_home:` not in the example file yet.

- [ ] **Step 3: Write minimal implementation**

Modify `config.example.yaml`. **Edit A** — bump the version (line 18):

```yaml
config_version: 13
```

**Edit B** — under the local-sandbox `sandbox:` block (after the `ls_output_max_chars` line ~829), add the user-home block:

```yaml
  # Per-user persistent home directory mount.
  # When enabled, {base_dir}/users/{user_id}/home/ is bind-mounted into the
  # sandbox at `container_path` (default /mnt/user-home). The directory lives
  # across thread lifecycles, sandbox container restarts, and gateway restarts.
  # This is the per-user counterpart to /mnt/user-data/{workspace,uploads,outputs}
  # (which is per-thread and ephemeral). See docx/superpowers/specs/2026-06-22-user-home-mount-design.md
  # for the full design.
  #
  # NOTE: When using AioSandboxProvider in remote-provisioning mode
  # (provisioner_url set), the provisioner currently drops extra_mounts from
  # the create payload (see community/aio_sandbox/remote_backend.py), so
  # user-home is NOT mounted in remote sandboxes. DeerFlow emits an actionable
  # ERROR log at startup in that combination. Full fix is Phase 2.
  user_home:
    enabled: true                  # Set to false to disable the mount + prompt section.
    container_path: /mnt/user-home # Virtual path inside the sandbox.
```

**Edit C** — under the AIO sandbox example block (around line 875), add the same `user_home` block as an example for AIO users. Find the line `# DeerFlow will surface configured container_path values to the agent,` and immediately after the `# - environment:` block, add a commented-out example. Concretely, locate the line `  #   environment:` and append after the closing of the environment example:

```yaml
  #   # Per-user persistent home — same semantics as the local-sandbox example above.
  #   user_home:
  #     enabled: true
  #     container_path: /mnt/user-home
```

(If you prefer to keep the AIO example shorter, add a one-line comment pointing at the local-sandbox example instead — but for clarity we duplicate.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && rtk pytest tests/test_sandbox_user_home_config.py -v`
Expected: PASS for all tests including the new example-config test.

Also run a sanity check on `make config-upgrade` (requires `config.yaml` to exist locally; skip if absent):

Run: `cd /Users/raidery/bench/harness/raidery/deer-flow && rtk make config-upgrade` (only if `config.yaml` exists — otherwise this will prompt to create one).
Expected: Either upgrades silently (good) or reports "no fields to upgrade" (good). No errors.

- [ ] **Step 5: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
rtk git add config.example.yaml backend/tests/test_sandbox_user_home_config.py
rtk git commit -m "docs(config): bump config_version to 13 + add sandbox.user_home example"
```

---

### Task 12: Cross-user isolation tests for `tools.py`

**Files:**
- Modify: `backend/tests/test_sandbox_tools_security.py` (extend)

**Interfaces:**
- Verifies: User A's `/mnt/user-home/` resolves to A's host dir, User B's resolves to B's. No cross-contamination even when threads interleave.

**Risks covered:** G4 (per-user isolation), R5 (correct user_id source — `get_effective_user_id()`, not `workspace_path` reverse-engineering), R7 (no stale cache).

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_sandbox_tools_security.py`:

```python
# ─────────────────────────────────────────────────────────────────
# user-home cross-user isolation (Phase 1, design G4 / R5 / R7)
# ─────────────────────────────────────────────────────────────────


def test_user_home_isolates_two_users_in_same_thread():
    """Two different users MUST see different host paths for the same virtual path."""
    from deerflow.sandbox.tools import _resolve_user_home_path

    td_alice = {"user_home_path": "/abs/users/alice/home", "user_home_container_path": "/mnt/user-home"}
    td_bob = {"user_home_path": "/abs/users/bob/home", "user_home_container_path": "/mnt/user-home"}

    alice_out = _resolve_user_home_path("/mnt/user-home/notes.md", td_alice)
    bob_out = _resolve_user_home_path("/mnt/user-home/notes.md", td_bob)

    assert alice_out == "/abs/users/alice/home/notes.md"
    assert bob_out == "/abs/users/bob/home/notes.md"
    assert alice_out != bob_out


def test_user_home_path_changes_with_effective_user_id():
    """Verify that re-resolving after a contextvar change gives a fresh host path.

    R7: this is exactly the failure mode of the skills single-instance cache if
    naively reused — the cache would serve User B's home path to User A.
    """
    from deerflow.sandbox.tools import _resolve_user_home_path
    from deerflow.runtime import user_context

    td_template = lambda uid: {  # noqa: E731
        "user_home_path": f"/abs/users/{uid}/home",
        "user_home_container_path": "/mnt/user-home",
    }

    token = user_context.set_current_user(SimpleNamespace(id="alice"))
    try:
        result_alice = _resolve_user_home_path("/mnt/user-home/x", td_template("alice"))
    finally:
        user_context.reset_current_user(token)

    token = user_context.set_current_user(SimpleNamespace(id="bob"))
    try:
        result_bob = _resolve_user_home_path("/mnt/user-home/x", td_template("bob"))
    finally:
        user_context.reset_current_user(token)

    assert "/users/alice/" in result_alice
    assert "/users/bob/" in result_bob
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && rtk pytest tests/test_sandbox_tools_security.py -v -k "user_home_isolates or user_home_path_changes"`
Expected: PASS (Task 6 already implemented `_resolve_user_home_path`, so these should pass immediately). If they pass, mark Step 2 complete and move on.

If a test FAILS here (e.g. `SimpleNamespace` import missing), add `from types import SimpleNamespace` to the top of `test_sandbox_tools_security.py` and re-run.

- [ ] **Step 3: No implementation changes needed**

If tests pass, document in the commit message that these are regression pins for design risks G4/R5/R7.

- [ ] **Step 4: Verify all sandbox tools tests pass**

Run: `cd backend && rtk pytest tests/test_sandbox_tools_security.py tests/test_local_sandbox_virtual_path_contract.py -v`
Expected: PASS, no regressions.

- [ ] **Step 5: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
rtk git add backend/tests/test_sandbox_tools_security.py
rtk git commit -m "test(sandbox): pin per-user isolation semantics for user-home (R5/R7)"
```

---

### Task 13: `delete_thread_dir` must NOT touch `home/`

**Files:**
- Modify: `backend/tests/test_delete_thread_dir_isolation.py` (create)

**Interfaces:**
- Verifies: after calling `Paths.delete_thread_dir(thread_id, user_id=user_id)`, the sibling directories `{base_dir}/users/{user_id}/home/`, `{base_dir}/users/{user_id}/memory.json`, `{base_dir}/users/{user_id}/agents/` are unchanged.

**Risks covered:** R6 (explicit assertion that `home/` survives thread deletion).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_delete_thread_dir_isolation.py`:

```python
"""``Paths.delete_thread_dir`` must delete only the thread subtree, never siblings.

Design risk R6 (2026-06-22): the existing implementation is ``shutil.rmtree`` on
the single thread_dir, which is structurally safe — but we pin the contract
with explicit assertions because ``shutil.rmtree`` is the kind of footgun that
future refactors (e.g. switching to a glob-based cleanup) would silently break.
"""
from __future__ import annotations

from pathlib import Path


def test_delete_thread_dir_preserves_user_home(tmp_path: Path) -> None:
    from deerflow.config.paths import Paths

    paths = Paths(base_dir=tmp_path)
    user_id = "alice"
    thread_id = "t-1"

    # Bootstrap a realistic per-user layout.
    paths.ensure_thread_dirs(thread_id, user_id=user_id)
    home = paths.user_home_dir(user_id)
    home.mkdir(parents=True, exist_ok=True)
    home_file = home / "notes.md"
    home_file.write_text("user content", encoding="utf-8")

    memory_file = paths.user_memory_file(user_id)
    memory_file.write_text("{}", encoding="utf-8")

    agents_dir = paths.user_agents_dir(user_id)
    agents_dir.mkdir(parents=True, exist_ok=True)
    (agents_dir / "sentinel").write_text("agent config", encoding="utf-8")

    # Act: delete the thread.
    paths.delete_thread_dir(thread_id, user_id=user_id)

    # Assert: thread subtree gone, siblings intact.
    assert not paths.thread_dir(thread_id, user_id=user_id).exists()
    assert home_file.exists() and home_file.read_text(encoding="utf-8") == "user content"
    assert memory_file.exists() and memory_file.read_text(encoding="utf-8") == "{}"
    assert (agents_dir / "sentinel").exists()


def test_delete_thread_dir_is_idempotent(tmp_path: Path) -> None:
    """Deleting a non-existent thread must not raise and must not affect siblings."""
    from deerflow.config.paths import Paths

    paths = Paths(base_dir=tmp_path)
    user_id = "bob"
    home = paths.user_home_dir(user_id)
    home.mkdir(parents=True, exist_ok=True)
    sentinel = home / "sentinel.md"
    sentinel.write_text("x", encoding="utf-8")

    # Should not raise even though the thread dir doesn't exist.
    paths.delete_thread_dir("nonexistent-thread", user_id=user_id)

    assert sentinel.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && rtk pytest tests/test_delete_thread_dir_isolation.py -v`
Expected: PASS (since `Paths.delete_thread_dir` is implemented correctly today at `paths.py:337-344`). If tests pass, this task is a regression pin only — no impl change needed.

If a test FAILS (e.g. the user-home dir was accidentally globbed), **STOP** and re-check `paths.py:337-344` — the implementation must remain `shutil.rmtree(thread_dir)` on a single Path, never a glob or walk that could expand to siblings.

- [ ] **Step 3: No implementation changes needed (regression pin)**

If tests pass, no code change. Document the contract.

- [ ] **Step 4: Verify**

Run: `cd backend && rtk pytest tests/test_delete_thread_dir_isolation.py -v`
Expected: PASS for both tests.

- [ ] **Step 5: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
rtk git add backend/tests/test_delete_thread_dir_isolation.py
rtk git commit -m "test(sandbox): pin delete_thread_dir isolation contract (R6)"
```

---

### Task 14: Documentation sync — `backend/CLAUDE.md` and root `CLAUDE.md`

**Files:**
- Modify: `backend/CLAUDE.md` — under the existing "Sandbox System" section, add a paragraph describing `/mnt/user-home/`.
- Modify: root `CLAUDE.md` — under "Sandbox Virtual Paths" section, add a row for `/mnt/user-home/`.

**Risks covered:** None (pure docs).

- [ ] **Step 1: Identify the exact insertion points**

In `backend/CLAUDE.md` (already viewed in conversation context), the "Sandbox System" section is after the long "Configuration System" block. Insert immediately after the **Virtual Path System** bullet list (which lists `/mnt/user-data/{workspace,uploads,outputs}`, `/mnt/skills`, `/mnt/acp-workspace`).

In root `CLAUDE.md` (project-level), the "Sandbox Virtual Paths" section is at line ~125 area. Insert a new bullet after `/mnt/skills`.

- [ ] **Step 2: Write the docs**

**Edit A** — `backend/CLAUDE.md`. After the `Virtual Path System` bullet list, insert:

```markdown
- **Per-user persistent home** (`/mnt/user-home/`) — every user owns a persistent, read-write directory at `{base_dir}/users/{user_id}/home/`, bind-mounted into the sandbox at `/mnt/user-home/` (configurable via `sandbox.user_home.container_path`). It survives thread lifecycles, sandbox container restarts, and gateway restarts — the per-user counterpart to the per-thread `/mnt/user-data/` namespace. Set `sandbox.user_home.enabled=false` to disable. Subagents inherit transparently through `thread_data` — no extra mount wiring. NOTE: AIO provider's remote-provisioning mode (`provisioner_url` set) currently drops `extra_mounts` and does not actually mount user-home — the provider emits an actionable ERROR at startup in that combination; full fix is Phase 2.
```

**Edit B** — root `CLAUDE.md` `Sandbox Virtual Paths` table. Add a row:

```markdown
| `/mnt/user-home/*` | **每用户** | **用户** | **rw（新增）** |
```

The original table uses 4 columns; the new row matches the existing column widths.

- [ ] **Step 3: Verify docs render correctly**

Open both files in a viewer and confirm the inserts land in the right section. No automated test for prose docs; manual eyeballing is the gate.

- [ ] **Step 4: (Skip — no test for docs)**

- [ ] **Step 5: Commit**

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
rtk git add backend/CLAUDE.md CLAUDE.md
rtk git commit -m "docs(sandbox): document /mnt/user-home/ in backend and root CLAUDE.md"
```

---

### Task 15: Full validation — `make lint && make test`

**Files:**
- No code changes.
- Run: `cd backend && rtk make lint && rtk make test`.

- [ ] **Step 1: Run lint**

Run: `cd backend && rtk make lint`
Expected: PASS. If `ruff` complains about a newly added file, fix the lint error in that file (likely a line length or import ordering issue).

- [ ] **Step 2: Run full test suite**

Run: `cd backend && rtk make test`
Expected: PASS — all existing tests plus the new tests from Tasks 1-14. No regressions.

If a pre-existing test breaks: investigate whether the change in this plan introduced a contract drift. Likely candidates: existing tests that construct `ThreadDataState` literally without the new keys (these should still pass — NotRequired) or that mock `_get_thread_paths` (these may need updating if the mock signature changed).

- [ ] **Step 3: Re-run new-feature tests in isolation**

Run: `cd backend && rtk pytest tests/test_user_home_dir.py tests/test_sandbox_user_home_config.py tests/test_thread_data_state_user_home.py tests/test_thread_data_middleware_user_home.py tests/test_user_home_path_helpers.py tests/test_sandbox_tools_security.py tests/test_local_sandbox_virtual_path_contract.py tests/test_aio_sandbox_provider.py tests/test_lead_agent_user_home_prompt.py tests/test_delete_thread_dir_isolation.py -v`
Expected: PASS for all.

- [ ] **Step 4: Commit (only if lint or test fixes were applied)**

If Steps 1-3 surfaced no issues, no commit is needed. If lint or test fixes were needed:

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
rtk git add <files-fixed>
rtk git commit -m "chore(sandbox): address lint + test fallout from user-home mount"
```

- [ ] **Step 5: Done**

Plan complete. Next step is review and landing via the user's standard PR flow.

---

## Cross-Reference: Spec → Task Coverage

| Spec element | Covered by |
|---|---|
| **G1** Per-user, persistent, writable mount at `/mnt/user-home/` | Tasks 1, 4, 7, 8 |
| **G2** Files survive across threads, container restarts, gateway restarts | Tasks 4, 7, 8 (host dir is on disk; no thread-scoped cleanup touches it) |
| **G3** Backward-compatible — `/mnt/user-data/...` unchanged | Task 6 (additive entry points), Task 11 (config defaults) |
| **G4** Per-user sandbox isolation, no cross-user leak | Task 12 (cross-user isolation tests) |
| **G5** Minimal diff — config + sandbox + middleware + tools + prompt + 2 docs | All tasks touch only files listed in the design |
| **NG1** Don't replace `/mnt/user-data/...` | All tasks preserve existing semantics |
| **NG2** Don't change skills mount semantics | No skills code changes |
| **NG3** No new DB tables | All persistence is filesystem-based |
| **NG4** Don't resolve PVC vs hostPath | Out of scope — documented |
| **NG5** No cross-host sync | Out of scope — documented |
| **Success #1** Files persist across threads | Task 4 + Tasks 7/8 (host dir is per-user, not per-thread) |
| **Success #2** Installed CLI binaries persist | Same as #1 |
| **Success #3** New thread's `home/` auto-created | Tasks 4 (mkdir on first access), 7-8 (mapping when exists) |
| **Success #4** `delete_thread_dir` doesn't touch `home/` | Task 13 (explicit assertion) |
| **Success #5** Two users get isolated `home/` | Task 12 |
| **Success #6** All existing tests pass | Task 15 |
| **Success #7** AIO remote provisioning has explicit warning | Task 9 |
| **R1** Disk full — documentation only | Task 14 (docs) |
| **R2** Permission drift — lock to `0o777` | Task 1 (`Paths.user_home_dir` consumer in Task 4 chmods) |
| **R3** Cross-mount reasoning confusion | Task 10 (prompt explicitly separates user-data / user-home / memory) |
| **R4** Skill contract broken | No skill code changes — pure additive |
| **R5** AIO remote drops `extra_mounts` | Task 9 (warning only — fix is Phase 2) |
| **R6** `delete_thread_dir` could touch `home/` | Task 13 |
| **R7** Host path with `user_id` + skills single-instance cache | Task 5 (no module-level cache; resolves fresh per call), Task 12 (test asserts cross-user resolution) |
| **R8** Regex truncation on quoted paths with spaces | Task 10 (prompt warns skill authors; regex not fixed in Phase 1) |
