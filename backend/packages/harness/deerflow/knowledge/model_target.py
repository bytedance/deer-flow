"""RAG model-target resolution and its missing-fields verdict (spec 2026-09-23 default model D3/D10.1).

Every RAG role has its own declaration in the ``rag:`` block (``extract_model`` /
``judge_model`` / ``vlm_model``) and one RAG-wide default sits behind them. A caller picks
its own role declaration first and passes it in as ``name``; this module answers the half
they all share — the RAG default, else the first configured model — and, for a target the
user explicitly declared, whether that target is usable at all.

Deliberately pure and standalone: no SDK construction, no network, no Qdrant, and no read
of the global config singleton unless the caller hands one over. The RAG save path passes
``rag=`` the *pending* block it is about to write, because ``config.rag`` still carries the
file being replaced and would answer for the wrong configuration.

Name lookup is exact: an explicit role name is never replaced by a default (a typo must
reach the factory and raise), and only the RAG default itself may be superseded — with a
warning that names it. A missing model list is not resolved here; the caller reports it.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from deerflow.config.models_config import reverse_lookup_provider

logger = logging.getLogger(__name__)

#: The protocol grid the strict rule covers: a UI-managed entry whose class maps to one of
#: these provider ids. The OpenAI-compatible cell is the only one that must name an address —
#: its SDK ships no readable default, while the vendor cells borrow theirs (spec D10.2).
_GRID_PROVIDERS = frozenset({"openai-compatible", "anthropic", "deepseek"})
_ADDRESS_REQUIRED_PROVIDERS = frozenset({"openai-compatible"})

#: Provider-side endpoint keys an entry may carry (the DeepSeek adapter uses ``api_base``).
_ENDPOINT_KEYS: tuple[str, ...] = ("base_url", "api_base")

#: The factory's sentence for a name that is not a configured entry. ``deerflow.models.factory``
#: raises it too; that file is frozen, so this is the one copy the RAG side is allowed to use --
#: a test drives the real factory to keep the two equal, and the callers must not spell the
#: sentence out themselves.
_NOT_FOUND_PREFIX = "Model "
_NOT_FOUND_SUFFIX = " not found in config"
_NOT_FOUND_TEMPLATE = f"{_NOT_FOUND_PREFIX}{{name}}{_NOT_FOUND_SUFFIX}"

#: The Chinese half of the same sentence (C-1, ② 已裁＝乙).
_NOT_FOUND_CN = "配置里没有模型「{name}」"


def model_not_found_message(name: str) -> str:
    """The sentence that says *name* is not a configured model (D9's not-found error)."""
    from deerflow.knowledge.messages import bilingual

    return bilingual(_NOT_FOUND_CN.format(name=name), _NOT_FOUND_TEMPLATE.format(name=name))


def missing_key_reason(name: str) -> str:
    """The sentence for a target whose entry carries no usable key (D10.1/R14)."""
    from deerflow.knowledge.messages import bilingual

    return bilingual(f"RAG 目标「{name}」不可用：条目缺少非空 api_key。", f'RAG target "{name}" is unusable: its entry carries no non-empty api_key.')


def missing_address_reason(name: str) -> str:
    """The sentence for the one cell that must name an address (D10.2)."""
    from deerflow.knowledge.messages import bilingual

    return bilingual(f"RAG 目标「{name}」不可用：openai-compatible 条目缺少接口地址（base_url）。", f'RAG target "{name}" is unusable: the openai-compatible entry declares no address (base_url).')


def is_model_not_found_error(exc: BaseException) -> bool:
    """Whether *exc* is that sentence — and nothing else (the CLI's narrow mapping, R28⑤)."""
    message = str(exc)
    return message.startswith(_NOT_FOUND_PREFIX) and message.endswith(_NOT_FOUND_SUFFIX)


def _declared(value: Any) -> str | None:
    """A non-blank string is a declaration; anything else means "not declared" (D2)."""
    if isinstance(value, str) and value.strip():
        return value
    return None


def _field(source: Any, name: str) -> Any:
    """Read one field from either a config object or a plain mapping."""
    if source is None:
        return None
    if isinstance(source, Mapping):
        return source.get(name)
    return getattr(source, name, None)


def _model_names(config: Any) -> list[str]:
    return [name for name in (getattr(model, "name", None) for model in (getattr(config, "models", None) or ())) if isinstance(name, str)]


def resolve_rag_model_name(config: Any, name: str | None = None, *, rag: Any = None) -> str | None:
    """Resolve one RAG role's target to a ``models:`` entry name.

    ``name`` is the caller's own role declaration (already chosen in D3's order). ``rag``
    overrides where the RAG default is read from. Returns ``None`` only when there is no
    model to name at all — the caller turns that into a configuration error rather than
    handing ``None`` to the factory, which would silently fall back to the first model.
    """
    explicit = _declared(name)
    if explicit is not None:
        return explicit

    names = _model_names(config)
    if not names:
        return None

    default = _declared(_field(rag if rag is not None else getattr(config, "rag", None), "default_model"))
    if default is None or default in names:
        return default or names[0]

    logger.warning(
        "RAG default model %r is not a configured model; using the first configured model %r instead.",
        default,
        names[0],
    )
    return names[0]


def require_rag_model_name(config: Any, name: str | None = None, *, rag: Any = None, role: str) -> str:
    """Resolve one RAG role's target, or refuse when there is no model to name.

    ``resolve_rag_model_name`` returns ``None`` so the "who reports this" decision stays with
    the caller; a RAG entry point turns it into a configuration error here rather than
    handing ``None`` to the factory, which would index an empty model list (D3). The error
    type is the RAG layer's one readable-configuration-failure signal, which the gateway
    already maps to a 400.
    """
    resolved = resolve_rag_model_name(config, name, rag=rag)
    if resolved is None:
        from deerflow.knowledge.embedder import RagConfigurationError
        from deerflow.knowledge.messages import bilingual

        cn = f"RAG 未配置可用模型：{role} 需要 config.models 里至少有一个条目，或为 rag.default_model 指定一个。"
        en = f"No usable RAG model is configured: {role} needs at least one entry under config.models, or one named by rag.default_model."
        raise RagConfigurationError(bilingual(cn, en))
    return resolved


def rag_target_missing(config: Any, declared: str | None, *, role: str) -> str | None:
    """Why the explicitly declared target *declared* cannot serve *role*, or ``None``.

    Pure: reads the entry through the config object, constructs nothing, goes nowhere. Three
    answers belong to somebody else and are therefore not this rule's error — a blank
    declaration is the system's own pick (D3), an entry outside the protocol grid or the UI
    source is the operator's own file, and a name that is not a configured entry is the
    not-found error the callers already have (D9). What is left is a UI-managed entry inside
    the grid that carries no usable key — or, for the OpenAI-compatible cell alone, no
    address (D10.2). The sentence names the entry and the missing field and nothing else, so
    every entrance reports the same thing for the same target (D10.1).
    """
    name = _declared(declared)
    if name is None:
        return None
    get_entry = getattr(config, "get_model_config", None)
    entry = get_entry(name) if callable(get_entry) else None
    if entry is None:
        return None
    is_ui = getattr(config, "is_ui_managed_model", None)
    if not callable(is_ui) or not is_ui(name):
        return None
    dumped = entry.model_dump() if hasattr(entry, "model_dump") else {}
    provider = reverse_lookup_provider((getattr(entry, "use", None) or dumped.get("use") or "").strip())
    if provider not in _GRID_PROVIDERS:
        return None
    if _declared(dumped.get("api_key")) is None:
        return missing_key_reason(name)
    if provider in _ADDRESS_REQUIRED_PROVIDERS and not any(dumped.get(key) for key in _ENDPOINT_KEYS):
        return missing_address_reason(name)
    return None


def require_usable_rag_target(config: Any, declared: str | None, *, role: str, rag: Any = None) -> str:
    """Resolve a role's target and refuse it when the entry it declares is unusable.

    The runtime entrances' one call: the name is resolved first (D3 — a wrong *name* still
    reaches the factory and raises there, D9), then the *declared* value is judged by
    :func:`rag_target_missing`. A blank declaration resolves to the system's own pick and is
    never judged; only what a caller or the ``rag:`` block actually named can be refused.
    """
    resolved = require_rag_model_name(config, declared, rag=rag, role=role)
    reason = rag_target_missing(config, _declared(declared), role=role)
    if reason is not None:
        from deerflow.knowledge.embedder import RagConfigurationError

        raise RagConfigurationError(reason)
    return resolved


def create_rag_chat_model(name: str, *, thinking: bool, app_config: Any = None, **kwargs):
    """The RAG legs' model constructor: chat's thinking treatment, with chat's entry gate.

    The legs never pass through the lead agent, and the factory *raises* on "thinking on"
    for an entry that declares no support instead of pressing back like chat does — so the
    gate is mirrored here (same downgrade, same warning) rather than inherited (spec
    2026-10-03 leg-thinking-follow-chat). The factory is called through its module
    attribute so tests can still patch it.
    """
    from deerflow.config.app_config import get_app_config
    from deerflow.models import factory as models_factory

    config = app_config if app_config is not None else get_app_config()
    model_config = config.get_model_config(name) if thinking else None
    if thinking and model_config is not None and not model_config.supports_thinking:
        logger.warning("Thinking mode is enabled but model '%s' does not support it; fallback to non-thinking mode.", name)
        thinking = False
    return models_factory.create_chat_model(name, thinking_enabled=thinking, app_config=config, **kwargs)
