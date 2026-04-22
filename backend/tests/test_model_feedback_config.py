"""Regression: ``model_feedback`` from YAML must parse as ``ModelFeedbackConfig``, not a raw dict."""

from __future__ import annotations

import asyncio

from deerflow.config.app_config import AppConfig
from deerflow.config.model_feedback_config import ModelFeedbackConfig
from deerflow.config.sandbox_config import SandboxConfig


def _minimal_sandbox_dict() -> dict:
    return {"use": "deerflow.sandbox.local:LocalSandboxProvider"}


def test_app_config_model_feedback_nested_dict_becomes_model() -> None:
    cfg = AppConfig.model_validate(
        {
            "sandbox": _minimal_sandbox_dict(),
            "model_feedback": {"enabled": True, "type": "memory"},
        }
    )
    assert isinstance(cfg.model_feedback, ModelFeedbackConfig)
    assert cfg.model_feedback.enabled is True
    assert cfg.model_feedback.type == "memory"


def test_app_config_model_feedback_omitted_is_none() -> None:
    cfg = AppConfig.model_validate({"sandbox": _minimal_sandbox_dict()})
    assert cfg.model_feedback is None


def test_native_model_feedback_store_accepts_valid_config() -> None:
    from deerflow.runtime.model_feedback.factory import native_model_feedback_store

    async def _run() -> None:
        mfc = ModelFeedbackConfig(enabled=True, type="memory")
        async with native_model_feedback_store(mfc) as store:
            assert store is not None

    asyncio.run(_run())
