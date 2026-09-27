from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from deerflow.config.app_config import AppConfig
from deerflow.config.reload_boundary import STARTUP_ONLY_FIELDS, STARTUP_ONLY_PREFIX
from deerflow.config.subagent_batches_config import SubagentBatchesConfig
from deerflow.config.subagent_runtime_config import SubagentRuntimeConfig
from deerflow.config.subagents_config import effective_subagent_concurrency


def test_subagent_runtime_defaults_are_safe_and_bounded() -> None:
    config = SubagentRuntimeConfig()
    assert config.max_running == 3
    assert config.max_queued == 64
    assert config.admission_policy == "queue"
    assert config.queue_timeout_seconds == 300

    with pytest.raises(ValidationError):
        SubagentRuntimeConfig(max_running=0)
    with pytest.raises(ValidationError):
        SubagentRuntimeConfig(max_running=65)
    with pytest.raises(ValidationError):
        SubagentRuntimeConfig(max_queued=10_001)


def test_subagent_batch_defaults_separate_total_live_and_running() -> None:
    config = SubagentBatchesConfig()
    assert config.enabled is False
    assert config.max_items_per_batch == 5_000
    assert config.default_max_live_items == 100
    assert config.default_max_running_items == 3

    with pytest.raises(ValidationError):
        SubagentBatchesConfig(default_max_live_items=5, default_max_running_items=6)
    with pytest.raises(ValidationError):
        SubagentBatchesConfig(max_live_items_per_batch=4, default_max_live_items=5)


def test_subagent_capacity_sections_are_startup_only() -> None:
    for name in ("subagent_runtime", "subagent_batches"):
        assert name in STARTUP_ONLY_FIELDS
        description = AppConfig.model_fields[name].description or ""
        assert description.startswith(STARTUP_ONLY_PREFIX)


def test_ordinary_task_limit_never_advertises_more_than_real_process_slots() -> None:
    config = SimpleNamespace(subagent_runtime=SubagentRuntimeConfig(max_running=8))
    assert effective_subagent_concurrency(None, config) == 8
    assert effective_subagent_concurrency(4, config) == 4
    assert effective_subagent_concurrency(50, config) == 8


def test_ordinary_task_limit_uses_frozen_execution_capacity_after_reload() -> None:
    reloaded_config = SimpleNamespace(subagent_runtime=SubagentRuntimeConfig(max_running=12))
    assert effective_subagent_concurrency(None, reloaded_config, execution_capacity=3) == 3
    assert effective_subagent_concurrency(10, reloaded_config, execution_capacity=3) == 3
