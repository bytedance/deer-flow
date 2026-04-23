import logging

from langchain.chat_models import BaseChatModel

from deerflow.config import get_app_config
from deerflow.reflection import resolve_class
from deerflow.runtime.model_feedback import record_model_feedback, record_model_feedback_sync
from deerflow.tracing import build_tracing_callbacks

logger = logging.getLogger(__name__)


def _deep_merge_dicts(base: dict | None, override: dict) -> dict:
    """Recursively merge two dictionaries without mutating the inputs."""
    merged = dict(base or {})
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def _vllm_disable_chat_template_kwargs(chat_template_kwargs: dict) -> dict:
    """Build the disable payload for vLLM/Qwen chat template kwargs."""
    disable_kwargs: dict[str, bool] = {}
    if "thinking" in chat_template_kwargs:
        disable_kwargs["thinking"] = False
    if "enable_thinking" in chat_template_kwargs:
        disable_kwargs["enable_thinking"] = False
    return disable_kwargs


def _wrap_model_feedback_hooks(model_instance: BaseChatModel, model_name: str) -> None:
    """Count every concrete provider call made through this model instance."""
    _wrap_sync_model_method(model_instance, "_generate", model_name)
    _wrap_async_model_method(model_instance, "_agenerate", model_name, skip_if_base=BaseChatModel._agenerate)
    _wrap_sync_stream_method(model_instance, "_stream", model_name, skip_if_base=BaseChatModel._stream)
    _wrap_async_stream_method(model_instance, "_astream", model_name, skip_if_base=BaseChatModel._astream)


def _resolved_model_method(model_instance: BaseChatModel, attr: str):
    return getattr(type(model_instance), attr, None)


def _wrap_sync_model_method(model_instance: BaseChatModel, attr: str, model_name: str) -> None:
    raw = _resolved_model_method(model_instance, attr)
    if raw is None or raw is getattr(BaseChatModel, attr, None):
        return
    original = getattr(model_instance, attr, None)
    if original is None:
        return

    def wrapped(*args, **kwargs):
        try:
            result = original(*args, **kwargs)
        except Exception:
            record_model_feedback_sync(model_name, success=False)
            raise
        record_model_feedback_sync(model_name, success=True)
        return result

    object.__setattr__(model_instance, attr, wrapped)


def _wrap_async_model_method(model_instance: BaseChatModel, attr: str, model_name: str, *, skip_if_base) -> None:
    raw = _resolved_model_method(model_instance, attr)
    if raw is None or raw is skip_if_base:
        return
    original = getattr(model_instance, attr, None)
    if original is None:
        return

    async def wrapped(*args, **kwargs):
        try:
            result = await original(*args, **kwargs)
        except Exception:
            await record_model_feedback(model_name, success=False)
            raise
        await record_model_feedback(model_name, success=True)
        return result

    object.__setattr__(model_instance, attr, wrapped)


def _wrap_sync_stream_method(model_instance: BaseChatModel, attr: str, model_name: str, *, skip_if_base) -> None:
    raw = _resolved_model_method(model_instance, attr)
    if raw is None or raw is skip_if_base:
        return
    original = getattr(model_instance, attr, None)
    if original is None:
        return

    def wrapped(*args, **kwargs):
        try:
            iterator = iter(original(*args, **kwargs))
        except Exception:
            record_model_feedback_sync(model_name, success=False)
            raise

        def _iter():
            try:
                for chunk in iterator:
                    yield chunk
            except Exception:
                record_model_feedback_sync(model_name, success=False)
                raise
            record_model_feedback_sync(model_name, success=True)

        return _iter()

    object.__setattr__(model_instance, attr, wrapped)


def _wrap_async_stream_method(model_instance: BaseChatModel, attr: str, model_name: str, *, skip_if_base) -> None:
    raw = _resolved_model_method(model_instance, attr)
    if raw is None or raw is skip_if_base:
        return
    original = getattr(model_instance, attr, None)
    if original is None:
        return

    def wrapped(*args, **kwargs):
        iterator = original(*args, **kwargs)

        async def _aiter():
            try:
                async for chunk in iterator:
                    yield chunk
            except Exception:
                await record_model_feedback(model_name, success=False)
                raise
            await record_model_feedback(model_name, success=True)

        return _aiter()

    object.__setattr__(model_instance, attr, wrapped)


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
            "when_thinking_disabled",
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
    if not thinking_enabled:
        if model_config.when_thinking_disabled is not None:
            # User-provided disable settings take full precedence
            model_settings_from_config.update(model_config.when_thinking_disabled)
        elif has_thinking_settings and effective_wte.get("extra_body", {}).get("thinking", {}).get("type"):
            # OpenAI-compatible gateway: thinking is nested under extra_body
            model_settings_from_config["extra_body"] = _deep_merge_dicts(
                model_settings_from_config.get("extra_body"),
                {"thinking": {"type": "disabled"}},
            )
            model_settings_from_config["reasoning_effort"] = "minimal"
        elif has_thinking_settings and (disable_chat_template_kwargs := _vllm_disable_chat_template_kwargs(effective_wte.get("extra_body", {}).get("chat_template_kwargs") or {})):
            # vLLM uses chat template kwargs to switch thinking on/off.
            model_settings_from_config["extra_body"] = _deep_merge_dicts(
                model_settings_from_config.get("extra_body"),
                {"chat_template_kwargs": disable_chat_template_kwargs},
            )
        elif has_thinking_settings and effective_wte.get("thinking", {}).get("type"):
            # Native langchain_anthropic: thinking is a direct constructor parameter
            model_settings_from_config["thinking"] = {"type": "disabled"}
    if not model_config.supports_reasoning_effort:
        kwargs.pop("reasoning_effort", None)
        model_settings_from_config.pop("reasoning_effort", None)

    # For Codex Responses API models: map thinking mode to reasoning_effort
    from deerflow.models.openai_codex_provider import CodexChatModel

    if issubclass(model_class, CodexChatModel):
        # The ChatGPT Codex endpoint currently rejects max_tokens/max_output_tokens.
        model_settings_from_config.pop("max_tokens", None)

        # Use explicit reasoning_effort from frontend if provided (low/medium/high)
        explicit_effort = kwargs.pop("reasoning_effort", None)
        if not thinking_enabled:
            model_settings_from_config["reasoning_effort"] = "none"
        elif explicit_effort and explicit_effort in ("low", "medium", "high", "xhigh"):
            model_settings_from_config["reasoning_effort"] = explicit_effort
        elif "reasoning_effort" not in model_settings_from_config:
            model_settings_from_config["reasoning_effort"] = "medium"

    # Ensure stream_usage is enabled so that token usage metadata is available
    # in streaming responses.  LangChain's BaseChatOpenAI only defaults
    # stream_usage=True when no custom base_url/api_base is set, so models
    # hitting third-party endpoints (e.g. doubao, deepseek) silently lose
    # usage data.  We default it to True unless explicitly configured.
    if "stream_usage" not in model_settings_from_config and "stream_usage" not in kwargs:
        if "stream_usage" in getattr(model_class, "model_fields", {}):
            model_settings_from_config["stream_usage"] = True

    model_instance = model_class(**kwargs, **model_settings_from_config)

    _wrap_model_feedback_hooks(model_instance, name)

    _wrap_model_feedback_hooks(model_instance, name)

    callbacks = build_tracing_callbacks()
    if callbacks:
        existing_callbacks = model_instance.callbacks or []
        model_instance.callbacks = [*existing_callbacks, *callbacks]
        logger.debug(f"Tracing attached to model '{name}' with providers={len(callbacks)}")
    return model_instance
