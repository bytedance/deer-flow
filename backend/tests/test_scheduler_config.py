"""Tests for SchedulerConfig schema."""

import pytest
from pydantic import ValidationError

from deerflow.config.scheduler_config import SchedulerConfig


def test_scheduler_config_defaults():
    config = SchedulerConfig()

    assert config.enabled is False
    assert config.recursion_limit == 1000
    assert config.max_concurrent_runs == 3
    assert config.max_concurrent_runs_per_user == 2


def test_scheduler_config_accepts_positive_recursion_limit():
    assert SchedulerConfig(recursion_limit=1).recursion_limit == 1
    assert SchedulerConfig(recursion_limit=1000).recursion_limit == 1000


def test_scheduler_config_rejects_non_positive_recursion_limit():
    with pytest.raises(ValidationError):
        SchedulerConfig(recursion_limit=0)

    with pytest.raises(ValidationError):
        SchedulerConfig(recursion_limit=-5)


def test_scheduler_config_per_user_cap_bounds():
    assert SchedulerConfig(max_concurrent_runs_per_user=0).max_concurrent_runs_per_user == 0
    assert SchedulerConfig(max_concurrent_runs_per_user=32).max_concurrent_runs_per_user == 32

    with pytest.raises(ValidationError):
        SchedulerConfig(max_concurrent_runs_per_user=-1)

    with pytest.raises(ValidationError):
        SchedulerConfig(max_concurrent_runs_per_user=33)
