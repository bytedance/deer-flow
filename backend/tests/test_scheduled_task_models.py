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
