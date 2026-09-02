#!/usr/bin/env python3
"""Explicit live entry point for DeerFlow model/tool compatibility checks."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from smoke import (
    CASES,
    CaseSpec,
    ConfigurationError,
    ErrorCategory,
    SmokeResult,
    evaluate_case,
    observe_events,
    redact_text,
    run_cli,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config.yaml"


def isolate_client_config(client: Any) -> None:
    """Install a process-local config copy with auxiliary model work disabled."""
    config = client._app_config
    isolated = config.model_copy(
        deep=True,
        update={
            "title": config.title.model_copy(
                deep=True,
                update={"enabled": False, "model_name": None},
            ),
            "summarization": config.summarization.model_copy(
                deep=True,
                update={"enabled": False, "model_name": None},
            ),
            "memory": config.memory.model_copy(
                deep=True,
                update={"enabled": False, "injection_enabled": False},
            ),
        },
    )
    client._app_config = isolated


def _invocation_error_category(exc: Exception) -> ErrorCategory:
    """Classify failures that escaped the normal model/tool middleware."""
    name = type(exc).__name__.lower()
    if isinstance(exc, (ImportError, ValueError)) or any(
        marker in name
        for marker in (
            "authentication",
            "credential",
            "permissiondenied",
            "configuration",
            "modelnotfound",
        )
    ):
        return ErrorCategory.CONFIGURATION
    if "sandbox" in name or "tool" in name:
        return ErrorCategory.TOOL_FAILURE
    if any(marker in name for marker in ("badrequest", "invalidrequest", "notimplemented", "unsupported")):
        return ErrorCategory.MODEL_INCOMPATIBLE
    return ErrorCategory.RUNNER


class DeerFlowRuntime:
    """Thin, injectable adapter around the embedded DeerFlow client."""

    cases = CASES

    def __init__(
        self,
        *,
        client_factory: Callable[[str | None], Any],
        set_user: Callable[[Any], Any],
        reset_user: Callable[[Any], None],
        delete_thread: Callable[[str, str], None],
    ) -> None:
        self._client_factory = client_factory
        self._set_user = set_user
        self._reset_user = reset_user
        self._delete_thread = delete_thread

    def _client(self, model: str | None) -> Any:
        try:
            return self._client_factory(model)
        except Exception as exc:
            raise ConfigurationError(f"could not initialize DeerFlowClient: {redact_text(exc)}") from exc

    def list_models(self) -> list[str]:
        try:
            payload = self._client(None).list_models()
            models = payload.get("models", []) if isinstance(payload, dict) else []
            names = [str(model["name"]) for model in models if isinstance(model, dict) and model.get("name")]
        except ConfigurationError:
            raise
        except Exception as exc:
            raise ConfigurationError(f"could not read configured models: {redact_text(exc)}") from exc
        if not names:
            raise ConfigurationError("config.yaml does not define any named models")
        return names

    def run_case(self, model: str, case: CaseSpec, thread_id: str, user_id: str) -> SmokeResult:
        token = self._set_user(SimpleNamespace(id=user_id))
        try:
            client = self._client(model)
            try:
                observation = observe_events(client.stream(case.prompt, thread_id=thread_id, user_id=user_id))
            except Exception as exc:
                category = _invocation_error_category(exc)
                return SmokeResult(
                    model=model,
                    case=case.name,
                    passed=False,
                    detail=f"model invocation raised {type(exc).__name__}: {redact_text(exc)}",
                    category=category,
                )

            artifact = None
            artifact_error = None
            if case.artifact_path:
                try:
                    artifact, _mime_type = client.get_artifact(thread_id, case.artifact_path)
                except Exception as exc:
                    artifact_error = f"{type(exc).__name__}: {redact_text(exc)}"
            return evaluate_case(
                model,
                case.name,
                observation,
                artifact=artifact,
                artifact_error=artifact_error,
            )
        finally:
            self._reset_user(token)

    def cleanup(self, thread_id: str, user_id: str) -> None:
        self._delete_thread(thread_id, user_id)


def _import_deerflow_runtime() -> tuple[Any, ...]:
    """Import live-only dependencies after the opt-in gate has passed."""
    from langgraph.checkpoint.memory import InMemorySaver

    from deerflow.client import DeerFlowClient
    from deerflow.config.paths import get_paths
    from deerflow.runtime.user_context import reset_current_user, set_current_user

    return DeerFlowClient, InMemorySaver, get_paths, set_current_user, reset_current_user


def make_runtime(
    config_path: Path = DEFAULT_CONFIG_PATH,
    *,
    importer: Callable[[], tuple[Any, ...]] = _import_deerflow_runtime,
) -> DeerFlowRuntime:
    """Build the live adapter without ever reading or printing `.env` values."""
    if not config_path.is_file():
        raise ConfigurationError(f"config.yaml not found at {config_path}")

    DeerFlowClient, InMemorySaver, get_paths, set_current_user, reset_current_user = importer()

    def client_factory(model: str | None) -> Any:
        client = DeerFlowClient(
            config_path=str(config_path),
            checkpointer=InMemorySaver(),
            model_name=model,
            thinking_enabled=False,
            subagent_enabled=False,
            plan_mode=False,
            available_skills=set(),
            environment="model-compat-smoke",
        )
        isolate_client_config(client)
        return client

    def delete_thread(thread_id: str, user_id: str) -> None:
        get_paths().delete_thread_dir(thread_id, user_id=user_id)

    return DeerFlowRuntime(
        client_factory=client_factory,
        set_user=set_current_user,
        reset_user=reset_current_user,
        delete_thread=delete_thread,
    )


def main(argv: list[str] | None = None) -> int:
    return int(run_cli(argv, runtime_factory=make_runtime))


if __name__ == "__main__":
    raise SystemExit(main())
