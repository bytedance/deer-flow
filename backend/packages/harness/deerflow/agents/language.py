"""Finite UI-language preferences; arbitrary client text is never rendered."""

from collections.abc import Mapping

UI_LANGUAGES = {"en-US": "English", "zh-CN": "Simplified Chinese"}


def ui_locale(context: object) -> str | None:
    value = context.get("locale") if isinstance(context, Mapping) else None
    return value if isinstance(value, str) and value in UI_LANGUAGES else None
