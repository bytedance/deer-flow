import pytest
from pydantic import ValidationError

from deerflow.config.app_config import AppConfig
from deerflow.config.mcp_tasks_config import McpTasksConfig
from deerflow.config.reload_boundary import STARTUP_ONLY_FIELDS, STARTUP_ONLY_PREFIX


def test_mcp_task_runtime_is_disabled_by_default_and_bounded():
    config = McpTasksConfig()
    assert config.enabled is False
    assert config.poll_interval_seconds == 5
    assert config.lease_seconds == 120
    assert config.max_concurrent_polls == 8

    with pytest.raises(ValidationError):
        McpTasksConfig(poll_interval_seconds=0)
    with pytest.raises(ValidationError):
        McpTasksConfig(max_concurrent_polls=0)


def test_mcp_task_runtime_is_registered_as_startup_only():
    assert "mcp_tasks" in STARTUP_ONLY_FIELDS
    field = AppConfig.model_fields["mcp_tasks"]
    assert (field.description or "").startswith(STARTUP_ONLY_PREFIX)
