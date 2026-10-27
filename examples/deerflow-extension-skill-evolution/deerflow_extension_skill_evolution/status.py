"""Read-only operational status, exposed through the plugin contribution.

The status action answers "is this deployment healthy" for operators: the
resolved config, whether the host still provides the ``skill_manage`` tool
this extension binds to, whether the deprecated core switch is still on, and
whether the operator granted this installation the host's guarded evolution
backbone — the mutation service and the sealed-evidence reader that
``mutations.py`` drives. It never returns skill content, other users' data,
credentials, or raw exception text, and it performs no writes — it cannot
grant or revoke any capability.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from deerflow_extension_skill_evolution.config import SkillEvolutionSettings
from deerflow_extension_skill_evolution.middleware import _legacy_core_switch_enabled
from deerflow_extension_skill_evolution.modes import read_evolution_mode
from deerflow_extension_skill_evolution.service import CapabilityHandle
from deerflow_extension_skill_evolution.tools import resolve_skill_manage_tool

NAMESPACE = "community.skill-evolution"


def _capability_status(handle: CapabilityHandle, fields: tuple[str, ...]) -> dict[str, Any]:
    service = handle.get()
    if service is None:
        # Either the operator did not grant this capability to this
        # installation, or the host predates the 0.2.7 capability field.
        return {"state": "not_granted"}
    if not fields:
        # Some granted services (e.g. the evidence reader) expose no
        # capabilities summary at all; granted/not_granted is the whole truth.
        return {"state": "granted"}
    try:
        capabilities = service.capabilities
        result = {"state": "granted"}
        for field in fields:
            value = getattr(capabilities, field)
            result[field] = list(value) if isinstance(value, tuple) else str(value)
        return result
    except Exception:
        # Deliberately not str(exc): exception text can carry host internals.
        return {"state": "granted", "capabilities": "unreadable"}


class StatusReporter:
    """Captures install-time settings; resolves live host capabilities per call."""

    def __init__(
        self,
        *,
        settings: SkillEvolutionSettings,
        extension_version: str,
        mutations_handle: CapabilityHandle,
        evidence_handle: CapabilityHandle,
        model_handle: CapabilityHandle | None = None,
        mode_reader: Callable[[], str] = read_evolution_mode,
    ) -> None:
        self._settings = settings
        self._extension_version = extension_version
        self._mutations_handle = mutations_handle
        self._evidence_handle = evidence_handle
        self._model_handle = model_handle
        self._mode_reader = mode_reader

    def snapshot(self, *, chat_models_available: bool = False) -> dict[str, Any]:
        try:
            resolve_skill_manage_tool()
            tool_status: str = "available"
        except Exception:
            # Deliberately not str(exc): exception text can carry host paths.
            tool_status = "unavailable"
        mutations = _capability_status(self._mutations_handle, ("operations", "protocol_version", "topology"))
        evidence = _capability_status(self._evidence_handle, ())
        # The annotation-triggered evolution jobs additionally need the
        # operator's model-invocation grant.
        if self._model_handle is None:
            model: dict[str, Any] = {"state": "not_granted"}
        else:
            model = _capability_status(self._model_handle, ())
        return {
            "product": "agent-evolution",
            "modules": [{"id": "skill", "state": "available"}, {"id": "memory", "state": "planned"}],
            "namespace": NAMESPACE,
            "distribution": "deerflow-extension-skill-evolution",
            "version": self._extension_version,
            "config": {
                "min_tool_calls_hint": self._settings.min_tool_calls_hint,
                "prefer_patch": self._settings.prefer_patch,
                "confirm_before_create": self._settings.confirm_before_create,
                "scope": self._settings.scope,
                "feedback_mode": self._settings.feedback_mode,
                # The user-facing evolution switch (settings JSON beside the
                # store), read live so the page always shows the current
                # mode. It supersedes the operator's feedback_mode.
                "evolution_mode": self._mode_reader(),
                # Agent feedback mode declares the skill_feedback tool only
                # when annotations have somewhere to live; the page surfaces
                # this mismatch to the operator.
                "feedback_storage": "configured" if self._settings.storage_path else "not_configured",
            },
            "host": {
                "skill_manage_tool": tool_status,
                "legacy_skill_evolution_enabled": _legacy_core_switch_enabled(),
                "skill_mutations": mutations,
                "completed_run_evidence": evidence,
                # The guarded pipeline in mutations.py needs both handles.
                "managed_pipeline": "available" if mutations["state"] == "granted" and evidence["state"] == "granted" else "unavailable",
                # Plan B's annotation-triggered jobs need the model grant too.
                "model_invocation": model,
                "chat_models": "available" if chat_models_available else "unavailable",
                "evolution_jobs": "available" if mutations["state"] == "granted" and evidence["state"] == "granted" and (chat_models_available or model["state"] == "granted") else "unavailable",
            },
            # Plugin loading is startup-only; there is nothing this action
            # could report that a restart would not also fix.
            "restart_required": False,
        }

    async def status(self, payload: Any, ctx: Any) -> dict[str, Any]:
        """``BackendAction`` handler: ignores the payload, returns the snapshot."""
        return self.snapshot(chat_models_available=getattr(ctx, "chat_models", None) is not None)
