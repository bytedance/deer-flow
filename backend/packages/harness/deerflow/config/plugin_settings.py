"""Validation of deployment-owned plugin configuration; no online overrides."""

import re
from typing import Any

from deerflow_extension_api.settings import FrontendBinding, SettingsContribution, SettingsField


def validate_value(field: SettingsField, value: Any) -> None:
    expected = {"boolean": bool, "integer": int, "string": str}.get(field.kind)
    if expected is None or type(value) is not expected:
        raise ValueError(f"{field.key}: expected {field.kind}")
    if field.kind == "integer" and ((field.minimum is not None and value < field.minimum) or (field.maximum is not None and value > field.maximum)):
        raise ValueError(f"{field.key}: outside allowed range")
    if field.kind == "string" and len(value) > field.max_length:
        raise ValueError(f"{field.key}: maximum length is {field.max_length}")


def validate_contribution(item: SettingsContribution) -> None:
    if not isinstance(item, SettingsContribution) or not re.fullmatch(r"[a-z][a-z0-9_.-]{0,95}", item.namespace):
        raise ValueError("Invalid settings contribution or namespace")
    if item.scope != "deployment" or item.applies not in {"next-run", "page-load", "next-request", "request-and-page-load"}:
        raise ValueError("Unsupported settings scope or application boundary")
    if not item.title or not 1 <= len(item.fields) <= 32:
        raise ValueError("Settings require a title and between 1 and 32 fields")
    seen = set()
    for field in item.fields:
        if not isinstance(field, SettingsField) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", field.key) or field.key in seen:
            raise ValueError("Invalid or duplicate settings field")
        seen.add(field.key)
        if not 1 <= field.max_length <= 4096:
            raise ValueError("Invalid string length bound")
        if field.minimum is not None and field.maximum is not None and field.minimum > field.maximum:
            raise ValueError("Invalid numeric bounds")
        validate_value(field, field.default)
    if item.frontend is not None:
        binding = item.frontend
        if not isinstance(binding, FrontendBinding) or not re.fullmatch(r"[a-z][a-z0-9.-]{0,95}", binding.module):
            raise ValueError("Invalid frontend module identifier")
        if len(set(binding.public_fields)) != len(binding.public_fields) or not set(binding.public_fields) <= seen:
            raise ValueError("Frontend fields must reference unique declared settings")
        enabled = next((field for field in item.fields if field.key == "enabled"), None)
        if enabled is None or enabled.kind != "boolean" or "enabled" not in binding.public_fields:
            raise ValueError("Frontend extensions require a public boolean enabled field")
        if item.applies not in {"page-load", "request-and-page-load"}:
            raise ValueError("Frontend extensions use page-load settings")


def defaults(item: SettingsContribution) -> dict[str, Any]:
    return {field.key: field.default for field in item.fields}
