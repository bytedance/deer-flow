"""Repo-wide guard: every numeric config field must reject a boolean.

Pydantic's lax mode coerces ``True``/``False`` into ``1``/``0`` for ``int`` and
``float`` fields *before* ``ge``/``le`` constraints run, so a stray YAML boolean
silently becomes a real limit instead of failing config load (#6017, #6293).
``max_input_tokens: true`` loads as 1, ``stream_ttl_seconds: false`` loads as 0,
and the value only surfaces as misbehaviour far from the typo.

Rather than reviewing each new field by hand, this module enumerates every
numeric field on every model in ``deerflow.config`` and asserts that both
``True`` and ``False`` are rejected. A new numeric field therefore cannot
reintroduce the gap without failing here.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import Any, get_args

import pytest
from pydantic import BaseModel, ValidationError

import deerflow.config as config_package

# Modules whose numeric fields are not guarded yet, with the fix each one is
# waiting on. Drop an entry once the guards land: from then on the module's
# fields must carry a ``reject_boolean`` guard, or the parametrized case below
# fails.
#
# ``mcp_tasks_config`` and ``subagent_batches_config`` have no fix in flight:
# their point fixes (#6289, #6291) were closed unmerged, and both modules are
# still fully unguarded on ``main``. This change is scoped to the modules the
# in-flight PRs do not touch, so they stay listed here rather than being folded
# in; the tracking issues (#6288, #6290) are still open.
MODULES_AWAITING_GUARDS: dict[str, str] = {
    "auth_config": "PR #6295 (open)",
    "mcp_tasks_config": "issue #6288; PR #6289 was closed unmerged",
    "subagent_batches_config": "issue #6290; PR #6291 was closed unmerged",
    "token_budget_config": "PR #6300 (open)",
    "tool_progress_config": "PR #6035 (open)",
}

# Modules that deliberately fall back to the documented default (with a warning
# naming the key) instead of failing config load. They still treat a boolean as
# invalid input, so they are covered by a dedicated test below.
GRACEFUL_FALLBACK_MODULES = frozenset({"projects_config"})

_NUMERIC_TYPES = (int, float)


def _is_numeric(annotation: Any) -> bool:
    """Whether ``annotation`` admits an int or float value (unions included).

    ``bool`` is an ``int`` subclass but is never a valid numeric config value, so
    it is excluded: a ``bool`` field is a switch, not a number.
    """
    if annotation is bool:
        return False
    if annotation in _NUMERIC_TYPES:
        return True
    for arg in get_args(annotation):
        if arg is bool:
            continue
        if _is_numeric(arg):
            return True
    return False


def _collect() -> list[tuple[str, str, str]]:
    """Enumerate ``(module, model, field)`` for every numeric config field."""
    cases: list[tuple[str, str, str]] = []
    for module_name in sorted(info.name for info in pkgutil.iter_modules(config_package.__path__)):
        if module_name.startswith("_"):
            continue
        module = importlib.import_module(f"{config_package.__name__}.{module_name}")
        for obj_name, obj in vars(module).items():
            if not inspect.isclass(obj) or not issubclass(obj, BaseModel):
                continue
            if obj.__module__ != module.__name__:
                continue  # imported here, defined elsewhere
            try:
                obj()
            except Exception:  # noqa: BLE001 - models with required fields are out of scope
                continue
            for field_name, field in obj.model_fields.items():
                if _is_numeric(field.annotation):
                    cases.append((module_name, obj_name, field_name))
    return cases


_CASES = _collect()


def _case_id(case: tuple[str, str, str]) -> str:
    module, model, field = case
    return f"{module}.{model}.{field}"


@pytest.mark.parametrize("case", _CASES, ids=[_case_id(case) for case in _CASES])
def test_numeric_config_field_rejects_boolean(case: tuple[str, str, str]) -> None:
    module_name, model_name, field_name = case
    if module_name in MODULES_AWAITING_GUARDS:
        pytest.skip(f"numeric guards not in place yet: {MODULES_AWAITING_GUARDS[module_name]}")
    if module_name in GRACEFUL_FALLBACK_MODULES:
        pytest.skip("covered by test_graceful_fallback_modules_drop_booleans")
    model = getattr(importlib.import_module(f"{config_package.__name__}.{module_name}"), model_name)
    for value in (True, False):
        with pytest.raises(ValidationError):
            model(**{field_name: value})


def test_enumeration_found_numeric_fields() -> None:
    """Guard against the enumeration silently going blind (e.g. an import error)."""
    assert len(_CASES) > 20, f"only {len(_CASES)} numeric config fields enumerated"


def test_graceful_fallback_modules_drop_booleans() -> None:
    """``projects`` keeps config load alive, but a boolean must not become a limit.

    ``ProjectsConfig._drop_invalid_values`` falls back to the documented default
    and logs a warning, so ``trash_retention_days: true`` must not resolve to a
    one-day retention window.
    """
    from deerflow.config.projects_config import ProjectsConfig

    defaults = ProjectsConfig()
    for value in (True, False):
        loaded = ProjectsConfig(instructions_max_bytes=value, trash_retention_days=value)
        assert loaded.instructions_max_bytes == defaults.instructions_max_bytes
        assert loaded.trash_retention_days == defaults.trash_retention_days
