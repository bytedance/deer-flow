"""Read-time sanitizer for model-incompatible content blocks in tool results.

The MCP tool-result conversion layer once persisted URL-sourced ``file``
content blocks (MCP ``ResourceLink`` results: ``ui://`` MCP App cards, local
files at ``/mnt/user-data/...`` virtual paths, remote non-image links) into
checkpointed ``ToolMessage`` content. When the selected model uses OpenAI Chat
Completions, every subsequent call fails during client-side message serialization:
langchain-core's OpenAI translator raises ``ValueError: OpenAI Chat Completions
does not support file URLs.`` for ANY ``file`` block carrying a ``url`` — the
Chat Completions API accepts file blocks only as base64 or file-id. The agent
loop classifies that as a generic, non-retriable failure, so every subsequent
turn answers with a fallback error:
the thread is permanently bricked.

The conversion layer no longer emits those blocks for new results. This
middleware covers the other time window — history written before the fix — by
rewriting the *request view* at the model boundary:

- a ``{"type": "file"}`` block carrying a ``url`` KEY becomes a plain text
  placeholder — ``[Resource ({mime or "unknown type"}) available at {url}]``
  when the URL is location-safe, ``[Resource ({mime or "unknown type"})]``
  otherwise (langchain-core raises on the key, not the value) — unless the
  selected model's serializer accepts http(s) file URLs (OpenAI Responses
  API ``input_file`` / Anthropic ``document`` URL), in which case the block
  is kept;
- an ``{"type": "image", "url": ...}`` block whose URL scheme the provider
  cannot fetch (anything outside ``http``/``https``/``data``) becomes the same
  placeholder — local images are meant to reach the model through the
  ``view_image`` tool, not as unresolvable URLs.

Placeholder text comes from ``resource_placeholder_text`` in
``deerflow.tools.resource_placeholder`` — the same formatter the conversion
layer uses — so a thread healed at read time shows the model the exact
placeholder shape a fresh conversion would have produced. The location segment
goes through the shared ``model_visible_location`` gate, also from that module:
virtual paths and remote schemes stay visible, while a raw ``file://`` URI, a
bare/Windows host path, or a ``data:``/``blob:`` URI (pre-fix blocks could carry
megabytes of inline base64 in a file URL) is withheld from model-visible text —
the same rules the conversion layer applies to fresh results. Interpolated
MIME/location metadata passes through the shared ``neutralize_untrusted_tags``
guard: this middleware runs after the input/tool-result sanitization passes,
and historical URL blocks never went through them (non-text content is left
untouched), so unguarded ``<system-reminder>``-style tags or boundary markers
in persisted metadata would otherwise reach the model verbatim.

The rewrite hooks ``wrap_model_call``/``awrap_model_call`` and hands the
handler an overridden request, exactly like ``ViewImageMiddleware``: nothing is
written to state, so checkpoints keep the original blocks (artifact capture and
other state readers are unaffected) and a poisoned thread heals itself on its
next turn with no migration. Artifact capture scans the original state messages,
so it never sees these request-only placeholders. The healer creates neither
``resource_links`` entries nor artifact handles; any captured references come
from the original tool result under the registry's own referenceability rules.
URLs withheld from the placeholder remain in the original checkpoint blocks;
the healer does not expose them through a new artifact entry.

The MCP conversion layer separately preserves downgraded ``ResourceLink``
results in ``ToolMessage.artifact["resource_links"]``, including unresolved host
locations, except ``data:``/``blob:`` links, which it drops. This structured
preservation happens during conversion of new results.

Scope is deliberately role-agnostic: every request message with list-form
content is rewritten, not just ``ToolMessage`` history. User uploads are
verified to produce base64 blocks — never URL-sourced file blocks — but
imported or cross-client history can carry a URL block on any role, and such a
block is unserializable under Chat Completions regardless of the role carrying
it. Widening the rule beyond ``ToolMessage`` therefore costs nothing and keeps
foreign history from bricking a thread. The rewrite is order-preserving and
idempotent — placeholder text blocks pass through unchanged on any later
application.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, override
from urllib.parse import urlparse

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AnyMessage

from deerflow.agents.middlewares.input_sanitization_middleware import neutralize_untrusted_tags
from deerflow.tools.resource_placeholder import model_visible_location, resource_placeholder_text

logger = logging.getLogger(__name__)

# URL schemes a chat model provider can resolve for image blocks. Everything
# else (``ui://``, scheme-less virtual paths, unknown schemes) is downgraded to
# a text reference. ``data:`` embeds the payload inline, so it is fetchable.
_FETCHABLE_IMAGE_SCHEMES = frozenset({"http", "https", "data"})


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _neutralize(value: str | None) -> str | None:
    """Neutralize framework/injection tokens in untrusted placeholder metadata.

    This middleware runs after the input/tool-result sanitization passes, and
    historical URL blocks never went through them (non-text content is left
    untouched), so MIME/location values interpolated into the placeholder must
    be guarded here — the same shared guard those passes apply.
    """
    return neutralize_untrusted_tags(value) if value else value


def _is_http_url(url: str) -> bool:
    try:
        return urlparse(url).scheme.lower() in ("http", "https")
    except ValueError:
        return False


def _accepts_http_file_urls(model: Any) -> bool:
    """Whether *model*'s request serializer accepts http(s) file URLs.

    Chat Completions rejects any URL-sourced ``file`` block, but the OpenAI
    Responses API (``input_file`` with ``file_url``) and Anthropic
    (``document`` with ``source.type == "url"``) accept HTTPS document URLs —
    a block persisted for those providers must survive the rewrite, or the
    document silently drops out of the model request.
    """
    if model is None:
        return False
    if getattr(model, "use_responses_api", False):
        return True
    return isinstance(model, ChatAnthropic)


def _sanitize_block(block: Any, model: Any) -> Any:
    """Return *block* unchanged, or its text-placeholder replacement.

    Identity is the unchanged signal for the caller: the same object comes back
    when nothing was rewritten.
    """
    if not isinstance(block, dict):
        return block
    block_type = block.get("type")
    if block_type == "file":
        # URL-sourced file blocks are rejected by Chat Completions whenever a
        # ``url`` KEY is present — langchain-core raises even for an empty
        # string or None — so gate on key presence, not truthiness. Base64 /
        # file_id blocks carry no ``url`` key and stay untouched. A present but
        # unusable URL ("" / None) gets a location-less placeholder.
        if "url" not in block:
            return block
        url = _str_or_none(block.get("url"))
        if url and _is_http_url(url) and _accepts_http_file_urls(model):
            # The selected provider serializes http(s) file URLs natively
            # (Responses API ``input_file`` / Anthropic ``document`` URL):
            # keep the block instead of dropping a readable document.
            return block
        return {"type": "text", "text": resource_placeholder_text(mime_type=_neutralize(_str_or_none(block.get("mime_type"))), url=_neutralize(model_visible_location(url)))}
    if block_type == "image":
        url = block.get("url")
        if not (isinstance(url, str) and url):
            return block
        try:
            scheme = urlparse(url).scheme.lower()
        except ValueError:
            # Structurally invalid URL (bad IPv6 literal, invalid netloc
            # characters): urlparse raises instead of returning a scheme.
            # Downgrade like any other non-fetchable location — one malformed
            # persisted URL must not raise on every model call and re-brick
            # the thread this middleware exists to heal.
            scheme = ""
        if scheme not in _FETCHABLE_IMAGE_SCHEMES:
            return {"type": "text", "text": resource_placeholder_text(mime_type=_neutralize(_str_or_none(block.get("mime_type"))), url=_neutralize(model_visible_location(url)))}
        return block
    return block


def _sanitize_message(message: AnyMessage, model: Any) -> AnyMessage:
    """Return *message* unchanged, or a copy with incompatible blocks replaced.

    Role-agnostic on purpose: any message with list-form content can carry a
    persisted or imported URL block that Chat Completions cannot serialize.
    """
    content = message.content
    if not isinstance(content, list):
        return message
    patched = [_sanitize_block(block, model) for block in content]
    if all(new is old for new, old in zip(patched, content, strict=True)):
        return message
    return message.model_copy(update={"content": patched})


def _sanitize_messages(messages: list[AnyMessage], model: Any) -> list[AnyMessage] | None:
    """Rewrite *messages* for the model request, or ``None`` when nothing changed."""
    updated: list[AnyMessage] = []
    changed = False
    for message in messages:
        patched = _sanitize_message(message, model)
        changed = changed or patched is not message
        updated.append(patched)
    return updated if changed else None


class ModelContentCompatibilityMiddleware(AgentMiddleware[AgentState]):
    """Downgrades persisted URL-sourced content blocks the model cannot accept.

    Request-view-only rewrite at the model boundary; see the module docstring
    for the failure mode and the contract. Stateless and config-free aside
    from the selected model's serializer capabilities, which gate only the
    http(s) file-URL preserve; the downgrade itself is unconditional.
    """

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        return handler(self._sanitize_request(request))

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        # Pure in-memory rewrite: no sandbox or file I/O, so it stays on the loop.
        return await handler(self._sanitize_request(request))

    @staticmethod
    def _sanitize_request(request: ModelRequest) -> ModelRequest:
        patched = _sanitize_messages(request.messages, request.model)
        if patched is None:
            return request
        return request.override(messages=patched)
