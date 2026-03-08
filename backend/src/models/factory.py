import logging

from langchain.chat_models import BaseChatModel

from src.config import get_app_config, get_tracing_config, is_tracing_enabled
from src.reflection import resolve_class

logger = logging.getLogger(__name__)


def create_chat_model(name: str | None = None, thinking_enabled: bool = False, **kwargs) -> BaseChatModel:
    """Create a chat model instance from the config.

    Args:
        name: The name of the model to create. If None, the first model in the config will be used.

    Returns:
        A chat model instance.
    """
    config = get_app_config()
    if name is None:
        name = config.models[0].name
    model_config = config.get_model_config(name)
    if model_config is None:
        raise ValueError(f"Model {name} not found in config") from None
    model_class = resolve_class(model_config.use, BaseChatModel)
    model_settings_from_config = model_config.model_dump(
        exclude_none=True,
        exclude={
            "use",
            "name",
            "display_name",
            "description",
            "supports_thinking",
            "supports_reasoning_effort",
            "when_thinking_enabled",
            "thinking",
            "supports_vision",
        },
    )
    # Compute effective when_thinking_enabled by merging in the `thinking` shortcut field.
    # The `thinking` shortcut is equivalent to setting when_thinking_enabled["thinking"].
    has_thinking_settings = (model_config.when_thinking_enabled is not None) or (model_config.thinking is not None)
    effective_wte: dict = dict(model_config.when_thinking_enabled) if model_config.when_thinking_enabled else {}
    if model_config.thinking is not None:
        merged_thinking = {**(effective_wte.get("thinking") or {}), **model_config.thinking}
        effective_wte = {**effective_wte, "thinking": merged_thinking}
    if thinking_enabled and has_thinking_settings:
        if not model_config.supports_thinking:
            raise ValueError(f"Model {name} does not support thinking. Set `supports_thinking` to true in the `config.yaml` to enable thinking.") from None
        if effective_wte:
            model_settings_from_config.update(effective_wte)
    if not thinking_enabled and has_thinking_settings:
        if effective_wte.get("extra_body", {}).get("thinking", {}).get("type"):
            # OpenAI-compatible gateway: thinking is nested under extra_body
            kwargs.update({"extra_body": {"thinking": {"type": "disabled"}}})
            kwargs.update({"reasoning_effort": "minimal"})
        elif effective_wte.get("thinking", {}).get("type"):
            # Native langchain_anthropic: thinking is a direct constructor parameter
            kwargs.update({"thinking": {"type": "disabled"}})
    if not model_config.supports_reasoning_effort:
        kwargs.update({"reasoning_effort": None})

    model_instance = model_class(**kwargs, **model_settings_from_config)

    if is_tracing_enabled():
        try:
            from langchain_core.tracers.langchain import LangChainTracer

            tracing_config = get_tracing_config()
            tracer = LangChainTracer(
                project_name=tracing_config.project,
            )
            existing_callbacks = model_instance.callbacks or []
            model_instance.callbacks = [*existing_callbacks, tracer]
            logger.debug(f"LangSmith tracing attached to model '{name}' (project='{tracing_config.project}')")
        except Exception as e:
            logger.warning(f"Failed to attach LangSmith tracing to model '{name}': {e}")
    return model_instance
