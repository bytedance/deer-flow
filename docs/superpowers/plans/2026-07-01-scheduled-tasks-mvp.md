# Scheduled Tasks MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a first-class scheduled-task MVP for DeerFlow with durable backend scheduling, a workspace management page, run history, and real-path validation, limited to thread-attached agent runs with `once` and `cron` schedules.

**Architecture:** Add harness persistence models and repositories for scheduled tasks and task-run history, then add an app-layer scheduler service and REST API that reuse the existing run lifecycle. Build a dedicated frontend workspace page and thread-level entry point backed by typed React Query hooks. Validate through backend tests, frontend tests, Playwright, and a real browser smoke path.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, Alembic, pytest, Next.js 16, React 19, TypeScript 5.8, TanStack Query, Playwright, pnpm, uv.

## Global Constraints

- The MVP supports only thread-attached agent runs; there is no text-only task type, no channel dispatch, and no GitHub dispatch.
- The MVP supports only `once` and `cron`; it must not add `interval`.
- Scheduled executions must reuse the normal DeerFlow run lifecycle rather than introducing a parallel agent execution path.
- Harness persistence code must not import `app.*`.
- Background scheduling remains opt-in through config and must default to disabled.
- Owner isolation must cover task list, task detail, task history, mutate, trigger, and delete.
- Completion claims require fresh verification evidence: backend tests, frontend tests, Playwright, and one real-path browser validation.

---

### Task 1: Add scheduler config and persistence skeleton

**Files:**
- Create: `backend/packages/harness/deerflow/config/scheduler_config.py`
- Modify: `backend/packages/harness/deerflow/config/app_config.py`
- Modify: `backend/packages/harness/deerflow/config/reload_boundary.py`
- Modify: `backend/packages/harness/deerflow/persistence/models/__init__.py`
- Create: `backend/packages/harness/deerflow/persistence/scheduled_tasks/__init__.py`
- Create: `backend/packages/harness/deerflow/persistence/scheduled_tasks/model.py`
- Create: `backend/packages/harness/deerflow/persistence/scheduled_task_runs/__init__.py`
- Create: `backend/packages/harness/deerflow/persistence/scheduled_task_runs/model.py`
- Test: `backend/tests/test_scheduled_task_models.py`

**Interfaces:**
- Consumes: existing `AppConfig`, `Base`, and ORM registration pattern.
- Produces:
  - `SchedulerConfig` with fields:
    - `enabled: bool`
    - `poll_interval_seconds: int`
    - `lease_seconds: int`
    - `max_concurrent_runs: int`
    - `min_once_delay_seconds: int`
  - `ScheduledTaskRow`
  - `ScheduledTaskRunRow`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_scheduled_task_models.py`:

```python
from deerflow.config.app_config import AppConfig
from deerflow.persistence.models import ScheduledTaskRow, ScheduledTaskRunRow


def test_app_config_exposes_scheduler_section():
    config = AppConfig.model_validate(
        {
            "models": [],
            "sandbox": {"use": "local"},
        }
    )
    assert config.scheduler.enabled is False
    assert config.scheduler.poll_interval_seconds == 5
    assert config.scheduler.lease_seconds == 120


def test_scheduled_task_models_registered():
    assert ScheduledTaskRow.__tablename__ == "scheduled_tasks"
    assert ScheduledTaskRunRow.__tablename__ == "scheduled_task_runs"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd backend && PYTHONPATH=. uv run pytest tests/test_scheduled_task_models.py -v
```

Expected:
- fail because `AppConfig` has no `scheduler`
- fail because `ScheduledTaskRow` / `ScheduledTaskRunRow` do not exist

- [ ] **Step 3: Implement minimal config and model skeleton**

Create `backend/packages/harness/deerflow/config/scheduler_config.py`:

```python
from pydantic import BaseModel, Field


class SchedulerConfig(BaseModel):
    enabled: bool = Field(default=False)
    poll_interval_seconds: int = Field(default=5, ge=1, le=300)
    lease_seconds: int = Field(default=120, ge=5, le=3600)
    max_concurrent_runs: int = Field(default=3, ge=1, le=32)
    min_once_delay_seconds: int = Field(default=60, ge=1, le=86400)
```

Update `backend/packages/harness/deerflow/config/app_config.py` imports and fields:

```python
from deerflow.config.scheduler_config import SchedulerConfig
```

Add field inside `AppConfig`:

```python
    scheduler: SchedulerConfig = Field(
        default_factory=SchedulerConfig,
        description="Scheduled task runtime configuration",
    )
```

Create `backend/packages/harness/deerflow/persistence/scheduled_tasks/model.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


class ScheduledTaskRow(Base):
    __tablename__ = "scheduled_tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    thread_id: Mapped[str] = mapped_column(String(64), index=True)
    assistant_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    prompt: Mapped[str] = mapped_column(Text)
    schedule_type: Mapped[str] = mapped_column(String(16))
    schedule_spec: Mapped[dict] = mapped_column(JSON, default=dict)
    timezone: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="enabled", index=True)
    overlap_policy: Mapped[str] = mapped_column(String(16), default="skip")
    misfire_policy: Mapped[str] = mapped_column(String(16), default="run_once")
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    max_runs: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))
```

Create `backend/packages/harness/deerflow/persistence/scheduled_task_runs/model.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


class ScheduledTaskRunRow(Base):
    __tablename__ = "scheduled_task_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    thread_id: Mapped[str] = mapped_column(String(64), index=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    trigger: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
```

Create `__init__.py` files:

```python
from .model import ScheduledTaskRow

__all__ = ["ScheduledTaskRow"]
```

```python
from .model import ScheduledTaskRunRow

__all__ = ["ScheduledTaskRunRow"]
```

Update `backend/packages/harness/deerflow/persistence/models/__init__.py`:

```python
from deerflow.persistence.scheduled_task_runs.model import ScheduledTaskRunRow
from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow
```

Append to `__all__`:

```python
    "ScheduledTaskRow",
    "ScheduledTaskRunRow",
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd backend && PYTHONPATH=. uv run pytest tests/test_scheduled_task_models.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/packages/harness/deerflow/config/scheduler_config.py \
  backend/packages/harness/deerflow/config/app_config.py \
  backend/packages/harness/deerflow/persistence/models/__init__.py \
  backend/packages/harness/deerflow/persistence/scheduled_tasks/__init__.py \
  backend/packages/harness/deerflow/persistence/scheduled_tasks/model.py \
  backend/packages/harness/deerflow/persistence/scheduled_task_runs/__init__.py \
  backend/packages/harness/deerflow/persistence/scheduled_task_runs/model.py \
  backend/tests/test_scheduled_task_models.py
git commit -m "feat(scheduler): add scheduler config and scheduled task models"
```

---

### Task 2: Add Alembic migration and repository CRUD

**Files:**
- Create: `backend/packages/harness/deerflow/persistence/scheduled_tasks/sql.py`
- Create: `backend/packages/harness/deerflow/persistence/scheduled_task_runs/sql.py`
- Create: `backend/packages/harness/deerflow/persistence/migrations/versions/0002_scheduled_tasks.py`
- Modify: `backend/packages/harness/deerflow/persistence/scheduled_tasks/__init__.py`
- Modify: `backend/packages/harness/deerflow/persistence/scheduled_task_runs/__init__.py`
- Test: `backend/tests/test_scheduled_task_repository.py`

**Interfaces:**
- Consumes: `ScheduledTaskRow`, `ScheduledTaskRunRow`, async session factory.
- Produces:
  - `ScheduledTaskRepository`
  - `ScheduledTaskRunRepository`
  - task CRUD API and owner-scoped listing

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_scheduled_task_repository.py`:

```python
from datetime import UTC, datetime

import pytest

from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.scheduled_task_runs import ScheduledTaskRunRepository
from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository


@pytest.mark.asyncio
async def test_scheduled_task_repository_create_and_list(tmp_path):
    await init_engine_from_config({"backend": "sqlite", "sqlite_dir": str(tmp_path)})
    sf = get_session_factory()
    assert sf is not None

    repo = ScheduledTaskRepository(sf)
    created = await repo.create(
        task_id="task-1",
        user_id="user-1",
        thread_id="thread-1",
        assistant_id="lead_agent",
        title="Daily summary",
        prompt="Summarize this thread",
        schedule_type="cron",
        schedule_spec={"cron": "0 9 * * *"},
        timezone="Asia/Shanghai",
        next_run_at=datetime(2026, 7, 2, 1, 0, tzinfo=UTC),
    )

    assert created["id"] == "task-1"
    listed = await repo.list_by_user("user-1")
    assert [task["id"] for task in listed] == ["task-1"]

    await close_engine()


@pytest.mark.asyncio
async def test_scheduled_task_run_repository_records_history(tmp_path):
    await init_engine_from_config({"backend": "sqlite", "sqlite_dir": str(tmp_path)})
    sf = get_session_factory()
    assert sf is not None

    repo = ScheduledTaskRunRepository(sf)
    row = await repo.create(
        run_record_id="task-run-1",
        task_id="task-1",
        thread_id="thread-1",
        scheduled_for=datetime(2026, 7, 2, 1, 0, tzinfo=UTC),
        trigger="manual",
        status="queued",
    )

    assert row["id"] == "task-run-1"
    history = await repo.list_by_task("task-1")
    assert [entry["id"] for entry in history] == ["task-run-1"]

    await close_engine()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd backend && PYTHONPATH=. uv run pytest tests/test_scheduled_task_repository.py -v
```

Expected:
- fail because repositories do not exist and migration/table path is absent

- [ ] **Step 3: Implement repositories and migration**

Create `backend/packages/harness/deerflow/persistence/scheduled_tasks/sql.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.scheduled_tasks.model import ScheduledTaskRow
from deerflow.utils.time import coerce_iso


class ScheduledTaskRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _row_to_dict(row: ScheduledTaskRow) -> dict[str, Any]:
        data = row.to_dict()
        for key in ("created_at", "updated_at", "next_run_at", "last_run_at", "lease_expires_at"):
            if data.get(key) is not None:
                data[key] = coerce_iso(data[key])
        return data

    async def create(
        self,
        *,
        task_id: str,
        user_id: str,
        thread_id: str,
        assistant_id: str | None,
        title: str,
        prompt: str,
        schedule_type: str,
        schedule_spec: dict[str, Any],
        timezone: str,
        next_run_at: datetime | None,
    ) -> dict[str, Any]:
        row = ScheduledTaskRow(
            id=task_id,
            user_id=user_id,
            thread_id=thread_id,
            assistant_id=assistant_id,
            title=title,
            prompt=prompt,
            schedule_type=schedule_type,
            schedule_spec=schedule_spec,
            timezone=timezone,
            next_run_at=next_run_at,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def get(self, task_id: str, *, user_id: str) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.get(ScheduledTaskRow, task_id)
            if row is None or row.user_id != user_id:
                return None
            return self._row_to_dict(row)

    async def list_by_user(self, user_id: str) -> list[dict[str, Any]]:
        stmt = (
            select(ScheduledTaskRow)
            .where(ScheduledTaskRow.user_id == user_id)
            .order_by(ScheduledTaskRow.created_at.desc(), ScheduledTaskRow.id.desc())
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(row) for row in result.scalars()]
```

Create `backend/packages/harness/deerflow/persistence/scheduled_task_runs/sql.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.scheduled_task_runs.model import ScheduledTaskRunRow
from deerflow.utils.time import coerce_iso


class ScheduledTaskRunRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _row_to_dict(row: ScheduledTaskRunRow) -> dict[str, Any]:
        data = row.to_dict()
        for key in ("scheduled_for", "started_at", "finished_at", "created_at"):
            if data.get(key) is not None:
                data[key] = coerce_iso(data[key])
        return data

    async def create(
        self,
        *,
        run_record_id: str,
        task_id: str,
        thread_id: str,
        scheduled_for: datetime,
        trigger: str,
        status: str,
    ) -> dict[str, Any]:
        row = ScheduledTaskRunRow(
            id=run_record_id,
            task_id=task_id,
            thread_id=thread_id,
            scheduled_for=scheduled_for,
            trigger=trigger,
            status=status,
            created_at=datetime.now(UTC),
        )
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def list_by_task(self, task_id: str) -> list[dict[str, Any]]:
        stmt = (
            select(ScheduledTaskRunRow)
            .where(ScheduledTaskRunRow.task_id == task_id)
            .order_by(ScheduledTaskRunRow.created_at.desc(), ScheduledTaskRunRow.id.desc())
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(row) for row in result.scalars()]
```

Update package exports:

```python
from .model import ScheduledTaskRow
from .sql import ScheduledTaskRepository

__all__ = ["ScheduledTaskRow", "ScheduledTaskRepository"]
```

```python
from .model import ScheduledTaskRunRow
from .sql import ScheduledTaskRunRepository

__all__ = ["ScheduledTaskRunRow", "ScheduledTaskRunRepository"]
```

Create `backend/packages/harness/deerflow/persistence/migrations/versions/0002_scheduled_tasks.py` with `upgrade()` / `downgrade()` creating:

```python
op.create_table(
    "scheduled_tasks",
    ...
)
op.create_index("ix_scheduled_tasks_user_id", "scheduled_tasks", ["user_id"])
op.create_index("ix_scheduled_tasks_thread_id", "scheduled_tasks", ["thread_id"])
op.create_index("ix_scheduled_tasks_status", "scheduled_tasks", ["status"])
op.create_index("ix_scheduled_tasks_next_run_at", "scheduled_tasks", ["next_run_at"])

op.create_table(
    "scheduled_task_runs",
    ...
)
op.create_index("ix_scheduled_task_runs_task_id", "scheduled_task_runs", ["task_id"])
op.create_index("ix_scheduled_task_runs_thread_id", "scheduled_task_runs", ["thread_id"])
op.create_index("ix_scheduled_task_runs_status", "scheduled_task_runs", ["status"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd backend && PYTHONPATH=. uv run pytest tests/test_scheduled_task_repository.py tests/test_scheduled_task_models.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/packages/harness/deerflow/persistence/scheduled_tasks/__init__.py \
  backend/packages/harness/deerflow/persistence/scheduled_tasks/sql.py \
  backend/packages/harness/deerflow/persistence/scheduled_task_runs/__init__.py \
  backend/packages/harness/deerflow/persistence/scheduled_task_runs/sql.py \
  backend/packages/harness/deerflow/persistence/migrations/versions/0002_scheduled_tasks.py \
  backend/tests/test_scheduled_task_repository.py
git commit -m "feat(scheduler): add scheduled task repositories and migration"
```

---

### Task 3: Implement schedule parsing and next-run computation

**Files:**
- Create: `backend/packages/harness/deerflow/scheduler/__init__.py`
- Create: `backend/packages/harness/deerflow/scheduler/clock.py`
- Create: `backend/packages/harness/deerflow/scheduler/schedules.py`
- Test: `backend/tests/test_scheduled_task_schedules.py`

**Interfaces:**
- Produces:
  - `validate_timezone(timezone: str) -> str`
  - `normalize_cron_expression(expr: str) -> str`
  - `next_run_at(schedule_type: str, schedule_spec: dict[str, object], timezone_name: str, *, now: datetime) -> datetime | None`
  - `validate_once_time(...)`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_scheduled_task_schedules.py`:

```python
from datetime import UTC, datetime

import pytest

from deerflow.scheduler.schedules import (
    next_run_at,
    normalize_cron_expression,
    validate_timezone,
)


def test_validate_timezone_accepts_iana_name():
    assert validate_timezone("Asia/Shanghai") == "Asia/Shanghai"


def test_validate_timezone_rejects_unknown_name():
    with pytest.raises(ValueError):
        validate_timezone("Mars/Base")


def test_normalize_cron_accepts_five_fields():
    assert normalize_cron_expression("0 9 * * 1") == "0 9 * * 1"


def test_normalize_cron_rejects_seconds_field():
    with pytest.raises(ValueError):
        normalize_cron_expression("0 0 9 * * 1")


def test_next_run_at_for_once_returns_none_after_fire_time():
    now = datetime(2026, 7, 2, 2, 0, tzinfo=UTC)
    result = next_run_at(
        "once",
        {"run_at": "2026-07-02T01:00:00+00:00"},
        "UTC",
        now=now,
    )
    assert result is None


def test_next_run_at_for_cron_uses_timezone():
    now = datetime(2026, 7, 1, 0, 30, tzinfo=UTC)
    result = next_run_at(
        "cron",
        {"cron": "0 9 * * *"},
        "Asia/Shanghai",
        now=now,
    )
    assert result == datetime(2026, 7, 1, 1, 0, tzinfo=UTC)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd backend && PYTHONPATH=. uv run pytest tests/test_scheduled_task_schedules.py -v
```

Expected: fail because `deerflow.scheduler.schedules` does not exist.

- [ ] **Step 3: Implement**

Create `backend/packages/harness/deerflow/scheduler/schedules.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter


def validate_timezone(timezone_name: str) -> str:
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown timezone: {timezone_name}") from exc
    return timezone_name


def normalize_cron_expression(expr: str) -> str:
    parts = [part for part in expr.split() if part]
    if len(parts) != 5:
        raise ValueError("Cron expression must contain exactly 5 fields")
    return " ".join(parts)


def next_run_at(
    schedule_type: str,
    schedule_spec: dict[str, object],
    timezone_name: str,
    *,
    now: datetime,
) -> datetime | None:
    validate_timezone(timezone_name)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    if schedule_type == "once":
        run_at_raw = schedule_spec.get("run_at")
        if not isinstance(run_at_raw, str):
            raise ValueError("once schedule requires run_at")
        run_at = datetime.fromisoformat(run_at_raw)
        if run_at.tzinfo is None:
            run_at = run_at.replace(tzinfo=UTC)
        return run_at if run_at > now else None

    if schedule_type == "cron":
        cron_expr = normalize_cron_expression(str(schedule_spec.get("cron", "")))
        zone = ZoneInfo(timezone_name)
        local_now = now.astimezone(zone)
        next_local = croniter(cron_expr, local_now).get_next(datetime)
        if next_local.tzinfo is None:
            next_local = next_local.replace(tzinfo=zone)
        return next_local.astimezone(UTC)

    raise ValueError(f"Unsupported schedule_type: {schedule_type}")
```

Create `backend/packages/harness/deerflow/scheduler/__init__.py`:

```python
from .schedules import next_run_at, normalize_cron_expression, validate_timezone

__all__ = ["next_run_at", "normalize_cron_expression", "validate_timezone"]
```

Create `backend/packages/harness/deerflow/scheduler/clock.py`:

```python
from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd backend && PYTHONPATH=. uv run pytest tests/test_scheduled_task_schedules.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/packages/harness/deerflow/scheduler/__init__.py \
  backend/packages/harness/deerflow/scheduler/clock.py \
  backend/packages/harness/deerflow/scheduler/schedules.py \
  backend/tests/test_scheduled_task_schedules.py
git commit -m "feat(scheduler): add schedule parsing and next-run computation"
```

---

### Task 4: Add due-claim, lease management, and task-run status updates

**Files:**
- Modify: `backend/packages/harness/deerflow/persistence/scheduled_tasks/sql.py`
- Modify: `backend/packages/harness/deerflow/persistence/scheduled_task_runs/sql.py`
- Test: `backend/tests/test_scheduled_task_claims.py`

**Interfaces:**
- Produces:
  - `claim_due_tasks(...)`
  - `release_lease(...)`
  - `mark_execution_result(...)`
  - `update_after_launch(...)`
  - `ScheduledTaskRunRepository.update_status(...)`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_scheduled_task_claims.py`:

```python
from datetime import UTC, datetime, timedelta

import pytest

from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository


@pytest.mark.asyncio
async def test_claim_due_tasks_claims_only_due_owned_rows(tmp_path):
    await init_engine_from_config({"backend": "sqlite", "sqlite_dir": str(tmp_path)})
    sf = get_session_factory()
    assert sf is not None
    repo = ScheduledTaskRepository(sf)

    due = datetime.now(UTC) - timedelta(minutes=1)
    future = datetime.now(UTC) + timedelta(hours=1)

    await repo.create(
        task_id="due-1",
        user_id="user-1",
        thread_id="thread-1",
        assistant_id="lead_agent",
        title="Due",
        prompt="Prompt",
        schedule_type="cron",
        schedule_spec={"cron": "0 9 * * *"},
        timezone="UTC",
        next_run_at=due,
    )
    await repo.create(
        task_id="future-1",
        user_id="user-1",
        thread_id="thread-1",
        assistant_id="lead_agent",
        title="Future",
        prompt="Prompt",
        schedule_type="cron",
        schedule_spec={"cron": "0 9 * * *"},
        timezone="UTC",
        next_run_at=future,
    )

    claimed = await repo.claim_due_tasks(
        now=datetime.now(UTC),
        lease_owner="worker-1",
        lease_seconds=120,
        limit=10,
    )
    assert [task["id"] for task in claimed] == ["due-1"]

    await close_engine()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd backend && PYTHONPATH=. uv run pytest tests/test_scheduled_task_claims.py -v
```

Expected: fail because `claim_due_tasks` does not exist.

- [ ] **Step 3: Implement**

Update `backend/packages/harness/deerflow/persistence/scheduled_tasks/sql.py` with:

```python
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_
```

Add methods:

```python
    async def claim_due_tasks(
        self,
        *,
        now: datetime,
        lease_owner: str,
        lease_seconds: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        lease_expires_at = now + timedelta(seconds=lease_seconds)
        stmt = (
            select(ScheduledTaskRow)
            .where(
                ScheduledTaskRow.status == "enabled",
                ScheduledTaskRow.next_run_at.is_not(None),
                ScheduledTaskRow.next_run_at <= now,
                or_(
                    ScheduledTaskRow.lease_expires_at.is_(None),
                    ScheduledTaskRow.lease_expires_at < now,
                ),
            )
            .order_by(ScheduledTaskRow.next_run_at.asc(), ScheduledTaskRow.id.asc())
            .limit(limit)
            .with_for_update()
        )
        async with self._sf() as session:
            result = await session.execute(stmt)
            rows = list(result.scalars())
            for row in rows:
                row.lease_owner = lease_owner
                row.lease_expires_at = lease_expires_at
                row.status = "running"
                row.updated_at = datetime.now(UTC)
            await session.commit()
            return [self._row_to_dict(row) for row in rows]

    async def release_lease(self, task_id: str, *, user_id: str | None = None) -> None:
        async with self._sf() as session:
            row = await session.get(ScheduledTaskRow, task_id)
            if row is None:
                return
            if user_id is not None and row.user_id != user_id:
                return
            row.lease_owner = None
            row.lease_expires_at = None
            row.updated_at = datetime.now(UTC)
            await session.commit()

    async def update_after_launch(
        self,
        task_id: str,
        *,
        status: str,
        next_run_at: datetime | None,
        last_run_at: datetime | None,
        last_run_id: str | None,
        last_error: str | None,
        increment_run_count: bool,
    ) -> None:
        async with self._sf() as session:
            row = await session.get(ScheduledTaskRow, task_id)
            if row is None:
                return
            row.status = status
            row.next_run_at = next_run_at
            row.last_run_at = last_run_at
            row.last_run_id = last_run_id
            row.last_error = last_error
            if increment_run_count:
                row.run_count += 1
            row.lease_owner = None
            row.lease_expires_at = None
            row.updated_at = datetime.now(UTC)
            await session.commit()
```

Update `backend/packages/harness/deerflow/persistence/scheduled_task_runs/sql.py`:

```python
    async def update_status(
        self,
        run_record_id: str,
        *,
        status: str,
        run_id: str | None = None,
        error: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> None:
        async with self._sf() as session:
            row = await session.get(ScheduledTaskRunRow, run_record_id)
            if row is None:
                return
            row.status = status
            row.run_id = run_id
            row.error = error
            if started_at is not None:
                row.started_at = started_at
            if finished_at is not None:
                row.finished_at = finished_at
            await session.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd backend && PYTHONPATH=. uv run pytest tests/test_scheduled_task_claims.py tests/test_scheduled_task_repository.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/packages/harness/deerflow/persistence/scheduled_tasks/sql.py \
  backend/packages/harness/deerflow/persistence/scheduled_task_runs/sql.py \
  backend/tests/test_scheduled_task_claims.py
git commit -m "feat(scheduler): add due-task claim and lease management"
```

---

### Task 5: Add scheduler service and shared run-launch helper

**Files:**
- Create: `backend/app/scheduler/__init__.py`
- Create: `backend/app/scheduler/service.py`
- Modify: `backend/app/gateway/services.py`
- Modify: `backend/app/gateway/deps.py`
- Test: `backend/tests/test_scheduled_task_service.py`

**Interfaces:**
- Produces:
  - `launch_scheduled_thread_run(...)`
  - `ScheduledTaskService`
  - `get_scheduled_task_service`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_scheduled_task_service.py`:

```python
from datetime import UTC, datetime, timedelta

import pytest

from app.scheduler.service import ScheduledTaskService


class DummyTaskRepo:
    def __init__(self, rows):
        self.rows = rows
        self.claimed = False

    async def claim_due_tasks(self, **_kwargs):
        if self.claimed:
            return []
        self.claimed = True
        return self.rows

    async def update_after_launch(self, *args, **kwargs):
        self.updated = (args, kwargs)


class DummyRunRepo:
    async def create(self, **kwargs):
        self.created = kwargs
        return {"id": kwargs["run_record_id"]}

    async def update_status(self, run_record_id, **kwargs):
        self.updated = (run_record_id, kwargs)


@pytest.mark.asyncio
async def test_service_claims_and_dispatches_due_task():
    async def fake_launch(**kwargs):
        return {"run_id": "run-1"}

    task_repo = DummyTaskRepo(
        [
            {
                "id": "task-1",
                "thread_id": "thread-1",
                "assistant_id": "lead_agent",
                "prompt": "Summarize thread",
                "schedule_type": "once",
                "schedule_spec": {"run_at": "2026-07-02T01:00:00+00:00"},
                "timezone": "UTC",
            }
        ]
    )
    run_repo = DummyRunRepo()
    service = ScheduledTaskService(
        task_repo=task_repo,
        task_run_repo=run_repo,
        launch_run=fake_launch,
        poll_interval_seconds=5,
        lease_seconds=120,
        max_concurrent_runs=3,
    )

    await service.run_once(now=datetime.now(UTC) + timedelta(days=1))

    assert run_repo.created["task_id"] == "task-1"
    assert run_repo.updated[1]["status"] == "success"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd backend && PYTHONPATH=. uv run pytest tests/test_scheduled_task_service.py -v
```

Expected: fail because service module does not exist.

- [ ] **Step 3: Implement**

Add helper to `backend/app/gateway/services.py`:

```python
async def launch_scheduled_thread_run(
    *,
    thread_id: str,
    assistant_id: str | None,
    prompt: str,
    request: Request,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body = SimpleNamespace(
        assistant_id=assistant_id,
        input={"messages": [{"role": "user", "content": prompt}]},
        command=None,
        metadata=metadata or {},
        config=None,
        context=None,
        webhook=None,
        checkpoint_id=None,
        checkpoint=None,
        interrupt_before=None,
        interrupt_after=None,
        stream_mode=None,
        stream_subgraphs=False,
        stream_resumable=None,
        on_disconnect="continue",
        on_completion="keep",
        multitask_strategy="reject",
        after_seconds=None,
        if_not_exists="reject",
        feedback_keys=None,
    )
    record = await start_run(
        request,
        thread_id,
        body,
        require_existing=True,
    )
    return {"run_id": record.run_id, "thread_id": record.thread_id}
```

Create `backend/app/scheduler/service.py`:

```python
from __future__ import annotations

import asyncio
import socket
import uuid
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable

from deerflow.scheduler.schedules import next_run_at


class ScheduledTaskService:
    def __init__(
        self,
        *,
        task_repo,
        task_run_repo,
        launch_run: Callable[..., Awaitable[dict[str, Any]]],
        poll_interval_seconds: int,
        lease_seconds: int,
        max_concurrent_runs: int,
    ) -> None:
        self._task_repo = task_repo
        self._task_run_repo = task_run_repo
        self._launch_run = launch_run
        self._poll_interval_seconds = poll_interval_seconds
        self._lease_seconds = lease_seconds
        self._max_concurrent_runs = max_concurrent_runs
        self._lease_owner = f"{socket.gethostname()}:{uuid.uuid4().hex}"
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def run_once(self, *, now: datetime) -> None:
        claimed = await self._task_repo.claim_due_tasks(
            now=now,
            lease_owner=self._lease_owner,
            lease_seconds=self._lease_seconds,
            limit=self._max_concurrent_runs,
        )
        for task in claimed:
            await self._dispatch_task(task, now=now)

    async def _dispatch_task(self, task: dict[str, Any], *, now: datetime) -> None:
        task_run_id = f"task-run-{uuid.uuid4().hex}"
        await self._task_run_repo.create(
            run_record_id=task_run_id,
            task_id=task["id"],
            thread_id=task["thread_id"],
            scheduled_for=now,
            trigger="scheduled",
            status="queued",
        )
        try:
            result = await self._launch_run(
                thread_id=task["thread_id"],
                assistant_id=task.get("assistant_id"),
                prompt=task["prompt"],
            )
            next_at = next_run_at(
                task["schedule_type"],
                task["schedule_spec"],
                task["timezone"],
                now=now,
            )
            status = "completed" if task["schedule_type"] == "once" else "enabled"
            await self._task_run_repo.update_status(
                task_run_id,
                status="success",
                run_id=result["run_id"],
                started_at=now,
                finished_at=now,
            )
            await self._task_repo.update_after_launch(
                task["id"],
                status=status,
                next_run_at=next_at,
                last_run_at=now,
                last_run_id=result["run_id"],
                last_error=None,
                increment_run_count=True,
            )
        except Exception as exc:
            await self._task_run_repo.update_status(
                task_run_id,
                status="failed",
                error=str(exc),
                started_at=now,
                finished_at=now,
            )
            await self._task_repo.update_after_launch(
                task["id"],
                status="failed" if task["schedule_type"] == "once" else "enabled",
                next_run_at=next_run_at(task["schedule_type"], task["schedule_spec"], task["timezone"], now=now),
                last_run_at=now,
                last_run_id=None,
                last_error=str(exc),
                increment_run_count=False,
            )

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop.set()
        await self._task
        self._task = None

    async def _run_loop(self) -> None:
        while not self._stop.is_set():
            await self.run_once(now=datetime.now(UTC))
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._poll_interval_seconds)
            except TimeoutError:
                continue
```

Create `backend/app/scheduler/__init__.py`:

```python
from .service import ScheduledTaskService

__all__ = ["ScheduledTaskService"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd backend && PYTHONPATH=. uv run pytest tests/test_scheduled_task_service.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/gateway/services.py \
  backend/app/scheduler/__init__.py \
  backend/app/scheduler/service.py \
  backend/tests/test_scheduled_task_service.py
git commit -m "feat(scheduler): add scheduled task service and shared run launcher"
```

---

### Task 6: Add scheduled-task API routes and app wiring

**Files:**
- Create: `backend/app/gateway/routers/scheduled_tasks.py`
- Modify: `backend/app/gateway/routers/__init__.py`
- Modify: `backend/app/gateway/app.py`
- Modify: `backend/app/gateway/deps.py`
- Test: `backend/tests/test_scheduled_task_router.py`

**Interfaces:**
- Produces REST endpoints:
  - list/create/detail/update/pause/resume/trigger/delete/history/thread-list

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_scheduled_task_router.py` with a minimal FastAPI app mounting the new router and stubbing repo dependencies:

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.routers import scheduled_tasks


def test_router_registers_list_endpoint():
    app = FastAPI()
    app.include_router(scheduled_tasks.router)
    client = TestClient(app)
    response = client.get("/api/scheduled-tasks")
    assert response.status_code != 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd backend && PYTHONPATH=. uv run pytest tests/test_scheduled_task_router.py -v
```

Expected: fail because router module does not exist.

- [ ] **Step 3: Implement minimal router and wiring**

Create `backend/app/gateway/routers/scheduled_tasks.py` with:

```python
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.gateway.authz import require_permission

router = APIRouter(prefix="/api", tags=["scheduled-tasks"])


class ScheduledTaskCreateRequest(BaseModel):
    thread_id: str
    title: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    schedule_type: str
    schedule_spec: dict[str, Any]
    timezone: str


@router.get("/scheduled-tasks")
@require_permission("threads", "read")
async def list_scheduled_tasks(request: Request):
    return []
```

Update router exports in `backend/app/gateway/routers/__init__.py`:

```python
from . import scheduled_tasks
```

Mount router in `backend/app/gateway/app.py` import list and `create_app()` include list.

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd backend && PYTHONPATH=. uv run pytest tests/test_scheduled_task_router.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/gateway/routers/scheduled_tasks.py \
  backend/app/gateway/routers/__init__.py \
  backend/app/gateway/app.py \
  backend/tests/test_scheduled_task_router.py
git commit -m "feat(scheduler): add scheduled task router skeleton"
```

---

### Task 7: Flesh out router behavior, owner isolation, and manual trigger

**Files:**
- Modify: `backend/app/gateway/routers/scheduled_tasks.py`
- Modify: `backend/app/gateway/deps.py`
- Test: `backend/tests/test_scheduled_task_router.py`

**Interfaces:**
- Produces working route handlers and dependency accessors:
  - `get_scheduled_task_repo`
  - `get_scheduled_task_run_repo`
  - `get_scheduled_task_service`

- [ ] **Step 1: Extend the failing tests**

Append to `backend/tests/test_scheduled_task_router.py`:

```python
def test_router_registers_trigger_route():
    app = FastAPI()
    app.include_router(scheduled_tasks.router)
    client = TestClient(app)
    response = client.post("/api/scheduled-tasks/task-1/trigger")
    assert response.status_code != 404
```

- [ ] **Step 2: Run tests to verify they fail correctly**

Run:

```bash
cd backend && PYTHONPATH=. uv run pytest tests/test_scheduled_task_router.py -v
```

Expected: fail because trigger route not implemented.

- [ ] **Step 3: Implement routes**

Add dependencies to `backend/app/gateway/deps.py`:

```python
def get_scheduled_task_repo(request: Request):
    val = getattr(request.app.state, "scheduled_task_repo", None)
    if val is None:
        raise HTTPException(status_code=503, detail="Scheduled task repo not available")
    return val


def get_scheduled_task_run_repo(request: Request):
    val = getattr(request.app.state, "scheduled_task_run_repo", None)
    if val is None:
        raise HTTPException(status_code=503, detail="Scheduled task run repo not available")
    return val


def get_scheduled_task_service(request: Request):
    val = getattr(request.app.state, "scheduled_task_service", None)
    if val is None:
        raise HTTPException(status_code=503, detail="Scheduled task service not available")
    return val
```

Expand `backend/app/gateway/routers/scheduled_tasks.py` with route stubs:

```python
@router.post("/scheduled-tasks")
@require_permission("threads", "write")
async def create_scheduled_task(request: Request, body: ScheduledTaskCreateRequest):
    return body.model_dump()


@router.get("/scheduled-tasks/{task_id}")
@require_permission("threads", "read")
async def get_scheduled_task(task_id: str):
    return {"id": task_id}


@router.patch("/scheduled-tasks/{task_id}")
@require_permission("threads", "write")
async def update_scheduled_task(task_id: str, request: Request, body: dict[str, Any]):
    return {"id": task_id, **body}


@router.post("/scheduled-tasks/{task_id}/pause")
@require_permission("threads", "write")
async def pause_scheduled_task(task_id: str):
    return {"id": task_id, "status": "paused"}


@router.post("/scheduled-tasks/{task_id}/resume")
@require_permission("threads", "write")
async def resume_scheduled_task(task_id: str):
    return {"id": task_id, "status": "enabled"}


@router.post("/scheduled-tasks/{task_id}/trigger")
@require_permission("threads", "write")
async def trigger_scheduled_task(task_id: str):
    return {"id": task_id, "triggered": True}


@router.delete("/scheduled-tasks/{task_id}")
@require_permission("threads", "write")
async def delete_scheduled_task(task_id: str):
    return {"id": task_id, "deleted": True}


@router.get("/scheduled-tasks/{task_id}/runs")
@require_permission("threads", "read")
async def list_scheduled_task_runs(task_id: str):
    return []


@router.get("/threads/{thread_id}/scheduled-tasks")
@require_permission("threads", "read", owner_check=True)
async def list_thread_scheduled_tasks(thread_id: str):
    return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd backend && PYTHONPATH=. uv run pytest tests/test_scheduled_task_router.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/gateway/deps.py \
  backend/app/gateway/routers/scheduled_tasks.py \
  backend/tests/test_scheduled_task_router.py
git commit -m "feat(scheduler): add scheduled task route surface"
```

---

### Task 8: Wire app state repositories and lifecycle start/stop

**Files:**
- Modify: `backend/app/gateway/deps.py`
- Modify: `backend/app/gateway/app.py`
- Test: `backend/tests/test_scheduled_task_lifecycle.py`

**Interfaces:**
- Produces app state members:
  - `scheduled_task_repo`
  - `scheduled_task_run_repo`
  - `scheduled_task_service`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_scheduled_task_lifecycle.py`:

```python
from app.gateway.app import create_app


def test_gateway_app_includes_scheduled_task_router():
    app = create_app()
    paths = {route.path for route in app.routes}
    assert "/api/scheduled-tasks" in paths
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd backend && PYTHONPATH=. uv run pytest tests/test_scheduled_task_lifecycle.py -v
```

Expected: fail if route inclusion or lifecycle wiring is incomplete.

- [ ] **Step 3: Implement**

In `backend/app/gateway/deps.py::langgraph_runtime`, after `thread_store` creation:

```python
        if sf is not None:
            from deerflow.persistence.scheduled_task_runs import ScheduledTaskRunRepository
            from deerflow.persistence.scheduled_tasks import ScheduledTaskRepository

            app.state.scheduled_task_repo = ScheduledTaskRepository(sf)
            app.state.scheduled_task_run_repo = ScheduledTaskRunRepository(sf)
        else:
            app.state.scheduled_task_repo = None
            app.state.scheduled_task_run_repo = None
```

In `backend/app/gateway/app.py::lifespan`, after channel service startup:

```python
        scheduled_task_service = None
        if getattr(startup_config.scheduler, "enabled", False):
            from app.scheduler import ScheduledTaskService
            from app.gateway.services import launch_scheduled_thread_run

            if (
                getattr(app.state, "scheduled_task_repo", None) is not None
                and getattr(app.state, "scheduled_task_run_repo", None) is not None
            ):
                scheduled_task_service = ScheduledTaskService(
                    task_repo=app.state.scheduled_task_repo,
                    task_run_repo=app.state.scheduled_task_run_repo,
                    launch_run=launch_scheduled_thread_run,
                    poll_interval_seconds=startup_config.scheduler.poll_interval_seconds,
                    lease_seconds=startup_config.scheduler.lease_seconds,
                    max_concurrent_runs=startup_config.scheduler.max_concurrent_runs,
                )
                app.state.scheduled_task_service = scheduled_task_service
                await scheduled_task_service.start()
```

Before exiting lifespan shutdown:

```python
        if getattr(app.state, "scheduled_task_service", None) is not None:
            try:
                await app.state.scheduled_task_service.stop()
            except Exception:
                logger.exception("Failed to stop scheduled task service")
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd backend && PYTHONPATH=. uv run pytest tests/test_scheduled_task_lifecycle.py tests/test_scheduled_task_router.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/gateway/deps.py backend/app/gateway/app.py backend/tests/test_scheduled_task_lifecycle.py
git commit -m "feat(scheduler): wire scheduled task repos and lifecycle"
```

---

### Task 9: Build frontend scheduled-task API layer and page shell

**Files:**
- Create: `frontend/src/core/scheduled-tasks/types.ts`
- Create: `frontend/src/core/scheduled-tasks/api.ts`
- Create: `frontend/src/core/scheduled-tasks/hooks.ts`
- Create: `frontend/src/app/workspace/scheduled-tasks/page.tsx`
- Modify: `frontend/src/components/workspace/workspace-nav-chat-list.tsx`
- Modify: `frontend/src/core/i18n/locales/types.ts`
- Modify: `frontend/src/core/i18n/locales/en-US.ts`
- Modify: `frontend/src/core/i18n/locales/zh-CN.ts`
- Test: `frontend/tests/unit/core/scheduled-tasks/hooks.test.ts`
- Test: `frontend/tests/e2e/scheduled-tasks.spec.ts`

**Interfaces:**
- Produces:
  - `ScheduledTask`
  - `ScheduledTaskRun`
  - `useScheduledTasks`
  - `/workspace/scheduled-tasks`

- [ ] **Step 1: Write the failing frontend tests**

Create `frontend/tests/e2e/scheduled-tasks.spec.ts`:

```typescript
import { expect, test } from "@playwright/test";

test("scheduled tasks page is reachable from sidebar", async ({ page }) => {
  await page.goto("/workspace/chats/new");
  await page.getByRole("link", { name: /scheduled tasks/i }).click();
  await page.waitForURL("**/workspace/scheduled-tasks");
  await expect(page).toHaveURL(/workspace\/scheduled-tasks/);
});
```

Create `frontend/tests/unit/core/scheduled-tasks/hooks.test.ts`:

```typescript
import { describe, expect, test } from "vitest";

import type { ScheduledTask } from "@/core/scheduled-tasks/types";

describe("scheduled task types", () => {
  test("scheduled task shape supports status and next run", () => {
    const task: ScheduledTask = {
      id: "task-1",
      thread_id: "thread-1",
      title: "Daily summary",
      prompt: "Summarize thread",
      schedule_type: "cron",
      schedule_spec: { cron: "0 9 * * *" },
      timezone: "UTC",
      status: "enabled",
      next_run_at: "2026-07-02T01:00:00+00:00",
      last_run_at: null,
      last_run_id: null,
      last_error: null,
      run_count: 0,
      created_at: "2026-07-01T00:00:00+00:00",
      updated_at: "2026-07-01T00:00:00+00:00",
    };

    expect(task.status).toBe("enabled");
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd frontend && pnpm test
cd frontend && pnpm test:e2e scheduled-tasks.spec.ts
```

Expected:
- fail because scheduled-task modules and route do not exist

- [ ] **Step 3: Implement page shell and hooks**

Create `frontend/src/core/scheduled-tasks/types.ts`:

```typescript
export type ScheduledTask = {
  id: string;
  thread_id: string;
  title: string;
  prompt: string;
  schedule_type: "once" | "cron";
  schedule_spec: Record<string, unknown>;
  timezone: string;
  status: "enabled" | "paused" | "running" | "completed" | "failed" | "cancelled";
  next_run_at: string | null;
  last_run_at: string | null;
  last_run_id: string | null;
  last_error: string | null;
  run_count: number;
  created_at: string;
  updated_at: string;
};

export type ScheduledTaskRun = {
  id: string;
  task_id: string;
  thread_id: string;
  run_id: string | null;
  scheduled_for: string;
  trigger: "scheduled" | "manual";
  status: "queued" | "running" | "success" | "failed" | "skipped";
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
};
```

Create `frontend/src/core/scheduled-tasks/api.ts`:

```typescript
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type { ScheduledTask, ScheduledTaskRun } from "./types";

export async function fetchScheduledTasks(): Promise<ScheduledTask[]> {
  const response = await fetch(`${getBackendBaseURL()}/api/scheduled-tasks`);
  return response.json();
}

export async function fetchThreadScheduledTasks(
  threadId: string,
): Promise<ScheduledTask[]> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/scheduled-tasks`,
  );
  return response.json();
}

export async function fetchScheduledTaskRuns(
  taskId: string,
): Promise<ScheduledTaskRun[]> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/scheduled-tasks/${encodeURIComponent(taskId)}/runs`,
  );
  return response.json();
}
```

Create `frontend/src/core/scheduled-tasks/hooks.ts`:

```typescript
import { useQuery } from "@tanstack/react-query";

import {
  fetchScheduledTaskRuns,
  fetchScheduledTasks,
  fetchThreadScheduledTasks,
} from "./api";

export function useScheduledTasks() {
  return useQuery({
    queryKey: ["scheduled-tasks"],
    queryFn: fetchScheduledTasks,
  });
}

export function useThreadScheduledTasks(threadId: string | null | undefined) {
  return useQuery({
    queryKey: ["scheduled-tasks", "thread", threadId],
    queryFn: () => fetchThreadScheduledTasks(threadId ?? ""),
    enabled: Boolean(threadId),
  });
}

export function useScheduledTaskRuns(taskId: string | null | undefined) {
  return useQuery({
    queryKey: ["scheduled-tasks", "runs", taskId],
    queryFn: () => fetchScheduledTaskRuns(taskId ?? ""),
    enabled: Boolean(taskId),
  });
}
```

Create `frontend/src/app/workspace/scheduled-tasks/page.tsx`:

```typescript
"use client";

import { useEffect } from "react";

import { WorkspaceBody, WorkspaceContainer, WorkspaceHeader } from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";
import { useScheduledTasks } from "@/core/scheduled-tasks/hooks";

export default function ScheduledTasksPage() {
  const { t } = useI18n();
  const { data } = useScheduledTasks();

  useEffect(() => {
    document.title = `${t.sidebar.scheduledTasks} - ${t.pages.appName}`;
  }, [t.pages.appName, t.sidebar.scheduledTasks]);

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody>
        <div className="mx-auto flex w-full max-w-(--container-width-md) flex-col gap-4 p-6">
          <h1 className="text-2xl font-semibold">{t.sidebar.scheduledTasks}</h1>
          <div data-testid="scheduled-task-list">
            {(data ?? []).map((task) => (
              <div key={task.id}>{task.title}</div>
            ))}
          </div>
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
```

Update sidebar types and translations with `scheduledTasks`.

Update `frontend/src/components/workspace/workspace-nav-chat-list.tsx` to add a link:

```typescript
import { CalendarClock, BotIcon, MessagesSquare } from "lucide-react";
```

Add menu item:

```typescript
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname.startsWith("/workspace/scheduled-tasks")}
            asChild
          >
            <Link
              className="text-muted-foreground"
              href="/workspace/scheduled-tasks"
            >
              <CalendarClock />
              <span>{t.sidebar.scheduledTasks}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd frontend && pnpm test
cd frontend && pnpm test:e2e scheduled-tasks.spec.ts
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/core/scheduled-tasks/types.ts \
  frontend/src/core/scheduled-tasks/api.ts \
  frontend/src/core/scheduled-tasks/hooks.ts \
  frontend/src/app/workspace/scheduled-tasks/page.tsx \
  frontend/src/components/workspace/workspace-nav-chat-list.tsx \
  frontend/src/core/i18n/locales/types.ts \
  frontend/src/core/i18n/locales/en-US.ts \
  frontend/src/core/i18n/locales/zh-CN.ts \
  frontend/tests/unit/core/scheduled-tasks/hooks.test.ts \
  frontend/tests/e2e/scheduled-tasks.spec.ts
git commit -m "feat(scheduler): add scheduled tasks workspace page shell"
```

---

### Task 10: Add thread-level scheduled-task entry point

**Files:**
- Modify: `frontend/src/app/workspace/chats/[thread_id]/page.tsx`
- Create: `frontend/src/components/workspace/thread-scheduled-tasks-link.tsx`
- Test: `frontend/tests/e2e/scheduled-tasks.spec.ts`

**Interfaces:**
- Produces a thread-scoped link to `/workspace/scheduled-tasks?thread_id=<id>`

- [ ] **Step 1: Extend the failing E2E test**

Append to `frontend/tests/e2e/scheduled-tasks.spec.ts`:

```typescript
test("thread page links to filtered scheduled tasks", async ({ page }) => {
  await page.goto("/workspace/chats/new");
  await page.goto("/workspace/chats/thread-1");
  await page.getByRole("link", { name: /scheduled tasks/i }).click();
  await page.waitForURL(/thread_id=thread-1/);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd frontend && pnpm test:e2e scheduled-tasks.spec.ts
```

Expected: fail because thread page has no such link.

- [ ] **Step 3: Implement**

Create `frontend/src/components/workspace/thread-scheduled-tasks-link.tsx`:

```typescript
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/core/i18n/hooks";

export function ThreadScheduledTasksLink({ threadId }: { threadId: string }) {
  const { t } = useI18n();
  return (
    <Button variant="outline" size="sm" asChild>
      <Link href={`/workspace/scheduled-tasks?thread_id=${encodeURIComponent(threadId)}`}>
        {t.sidebar.scheduledTasks}
      </Link>
    </Button>
  );
}
```

Import and render it in `frontend/src/app/workspace/chats/[thread_id]/page.tsx` near the header controls using the current `threadId`.

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd frontend && pnpm test:e2e scheduled-tasks.spec.ts
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/workspace/thread-scheduled-tasks-link.tsx \
  frontend/src/app/workspace/chats/[thread_id]/page.tsx \
  frontend/tests/e2e/scheduled-tasks.spec.ts
git commit -m "feat(scheduler): add thread-level scheduled task entry point"
```

---

### Task 11: Flesh out frontend page interactions and backend contract

**Files:**
- Modify: `backend/app/gateway/routers/scheduled_tasks.py`
- Modify: `frontend/src/core/scheduled-tasks/api.ts`
- Modify: `frontend/src/core/scheduled-tasks/hooks.ts`
- Modify: `frontend/src/app/workspace/scheduled-tasks/page.tsx`
- Test: `backend/tests/test_scheduled_task_router.py`
- Test: `frontend/tests/unit/core/scheduled-tasks/hooks.test.ts`
- Test: `frontend/tests/e2e/scheduled-tasks.spec.ts`

**Interfaces:**
- Produces working list/detail/create/update/pause/resume/trigger/delete flows

- [ ] **Step 1: Extend failing tests for CRUD and actions**

Add backend tests that assert response shapes and route presence for:
- create
- history
- pause/resume
- delete

Add Playwright interactions for:
- create modal/form submit
- pause/resume action buttons
- trigger action
- delete action

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd backend && PYTHONPATH=. uv run pytest tests/test_scheduled_task_router.py -v
cd frontend && pnpm test:e2e scheduled-tasks.spec.ts
```

Expected: fail because current page shell and route stubs do not implement these behaviors.

- [ ] **Step 3: Implement minimal full flow**

Backend:
- validate payloads
- read/write through repositories
- manual trigger delegates to scheduled task service or shared launch helper
- list history from `ScheduledTaskRunRepository`

Frontend:
- add create form
- add selected-task detail panel
- add action buttons and mutation hooks
- refresh list/history on success

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd backend && PYTHONPATH=. uv run pytest tests/test_scheduled_task_router.py tests/test_scheduled_task_service.py tests/test_scheduled_task_repository.py tests/test_scheduled_task_claims.py tests/test_scheduled_task_schedules.py -v
cd frontend && pnpm test
cd frontend && pnpm test:e2e scheduled-tasks.spec.ts
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/gateway/routers/scheduled_tasks.py \
  frontend/src/core/scheduled-tasks/api.ts \
  frontend/src/core/scheduled-tasks/hooks.ts \
  frontend/src/app/workspace/scheduled-tasks/page.tsx \
  backend/tests/test_scheduled_task_router.py \
  frontend/tests/unit/core/scheduled-tasks/hooks.test.ts \
  frontend/tests/e2e/scheduled-tasks.spec.ts
git commit -m "feat(scheduler): implement scheduled task CRUD and UI actions"
```

---

### Task 12: Real-path validation, docs sync, and final verification

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `backend/AGENTS.md`
- Modify: `backend/docs/CONFIGURATION.md`
- Test: no new file required; use existing verification commands

**Interfaces:**
- Produces updated docs and final evidence package

- [ ] **Step 1: Update docs**

Add concise documentation for:
- what scheduled tasks MVP supports
- how to enable scheduler in config
- where users manage tasks in the workspace
- what is intentionally unsupported in MVP

- [ ] **Step 2: Run backend verification**

Run:

```bash
cd backend && PYTHONPATH=. uv run pytest \
  tests/test_scheduled_task_models.py \
  tests/test_scheduled_task_repository.py \
  tests/test_scheduled_task_schedules.py \
  tests/test_scheduled_task_claims.py \
  tests/test_scheduled_task_service.py \
  tests/test_scheduled_task_router.py \
  tests/test_scheduled_task_lifecycle.py -v
```

Expected: all PASS

- [ ] **Step 3: Run frontend verification**

Run:

```bash
cd frontend && pnpm test
cd frontend && pnpm check
cd frontend && pnpm test:e2e scheduled-tasks.spec.ts
```

Expected: all PASS

- [ ] **Step 4: Run real-path browser validation**

Run:

```bash
make dev
```

Then verify in a real browser:
- create a one-time scheduled task due soon
- observe list row and task detail
- observe task trigger and resulting DeerFlow run
- verify final status/result is reflected in the management page

- [ ] **Step 5: Commit**

```bash
git add README.md AGENTS.md backend/AGENTS.md backend/docs/CONFIGURATION.md
git commit -m "docs(scheduler): document scheduled tasks MVP"
```

---

### Task 13: Independent verifier pass before PR

**Files:**
- No code changes required; verifier may request fixes in touched files.

**Interfaces:**
- Produces fail-loud verification report covering:
  - skipped paths
  - warnings
  - not-yet-verified areas

- [ ] **Step 1: Dispatch a fresh verifier**

Give the verifier only:
- goal contract
- changed files
- exact verification commands

- [ ] **Step 2: Address verifier findings**

If findings exist:
- write failing test
- confirm fail
- implement fix
- rerun relevant verification

- [ ] **Step 3: Run final full verification**

Run:

```bash
cd backend && PYTHONPATH=. uv run pytest
cd frontend && pnpm check
cd frontend && pnpm test
cd frontend && pnpm test:e2e
```

Expected: pass or clearly documented existing unrelated failures

- [ ] **Step 4: Prepare PR**

PR body must include:
- goal contract
- test evidence
- real browser validation evidence
- verifier fail-loud report
- explicit skipped/not-verified items if any
