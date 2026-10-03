"""Shared ``mode="before"`` field validators that reject booleans for numeric config fields.

Pydantic coerces ``true``/``false`` into ``1``/``0`` for int and float fields, so a boolean in
config silently flips behavior — capping a loop at one step, disabling retries, serializing
concurrent calls, or skipping a health check (#6017, #6171). Register one guard per numeric
field instead of copying the check into another config file:

    @field_validator("max_concurrent_calls", mode="before")
    @classmethod
    def _reject_boolean_llm_call_settings(cls, value: object, info: ValidationInfo) -> object:
        return reject_boolean(value, info, kind="an integer")
"""

from __future__ import annotations

from pydantic import ValidationInfo


def reject_boolean(value: object, info: ValidationInfo, *, kind: str = "an integer") -> object:
    """Reject a boolean for the numeric config field named by ``info.field_name``.

    Args:
        value: the raw field value, before Pydantic's numeric coercion.
        info: the validation context carrying the field name.
        kind: the wording after "must be" — ``"an integer"`` for int fields,
            ``"a number"`` for float fields, or a custom phrase such as
            ``"a number of seconds or null"``.

    Raises:
        ValueError: when ``value`` is a bool. ``bool`` is an ``int`` subclass,
            so without this guard Pydantic coerces ``true``/``false`` into
            ``1``/``0`` before ``ge``/``le`` constraints ever run.
    """
    if isinstance(value, bool):
        raise ValueError(f"{info.field_name} must be {kind}, not a boolean")
    return value
