import re

from sqlalchemy import Index

from deerflow.config.app_config import AppConfig
from deerflow.domain.schedule.model import ACTIVE_RUN_STATUSES
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


def _active_run_index() -> Index:
    return next(arg for arg in ScheduledTaskRunRow.__table_args__ if isinstance(arg, Index) and arg.name == "uq_scheduled_task_run_active")


def test_active_run_index_arbitrates_one_active_run_per_task():
    """The index is the atomic arbiter of the overlap rule, so its shape is a
    contract, not a detail: unique, keyed on `task_id` alone."""
    index = _active_run_index()
    assert index.unique is True
    assert [column.name for column in index.expressions] == ["task_id"]


def test_active_run_index_predicate_matches_the_domain_constant():
    """`ACTIVE_RUN_STATUSES` and this predicate must stay in lockstep.

    The domain's fast path (`has_active`) and the index disagree the moment
    they drift, which silently decouples the overlap check from its arbiter.
    The domain tests cannot assert this -- they are deliberately
    dependency-free and cannot import an ORM model -- so the assertion the
    `ACTIVE_RUN_STATUSES` docstring promises lives here.

    Both dialect predicates are checked: `create_all` renders the SQLite one
    and production renders the Postgres one, so a drift in either is real.
    """
    index = _active_run_index()
    expected = {str(status) for status in ACTIVE_RUN_STATUSES}
    assert expected == {"queued", "running"}, "domain constant changed -- update the ORM predicates below"

    predicates = {key: str(value) for key, value in index.dialect_kwargs.items() if key.endswith("_where")}
    assert set(predicates) == {"sqlite_where", "postgresql_where"}, "a dialect lost its partial-index predicate"
    for dialect, predicate in predicates.items():
        assert set(re.findall(r"'([^']+)'", predicate)) == expected, f"{dialect} predicate drifted from ACTIVE_RUN_STATUSES"
