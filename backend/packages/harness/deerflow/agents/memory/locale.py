"""Capture the run preference without changing checkpoint or backend APIs."""

from deerflow.agents.language import ui_locale

_MEMORY_LOCALE_KEY = "deerflow_ui_locale"


def with_memory_locale(messages: list, context: object) -> list:
    locale = ui_locale(context)
    captured = []
    for message in messages:
        kwargs = {key: value for key, value in message.additional_kwargs.items() if key != _MEMORY_LOCALE_KEY}
        if locale is not None:
            kwargs[_MEMORY_LOCALE_KEY] = locale
        # Stamp every queued copy: filtering and the extraction watermark may
        # leave only an assistant tail. Never write this marker to graph state.
        captured.append(message.model_copy(update={"additional_kwargs": kwargs}) if kwargs != message.additional_kwargs else message)
    return captured
