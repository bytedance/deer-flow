"""Patched ChatOpenAI that preserves thought_signature for Gemini thinking models.

When using Gemini with thinking enabled via an OpenAI-compatible gateway (e.g.
Vertex AI, Google AI Studio, or any proxy), the API requires that the
``thought_signature`` field on tool-call objects is echoed back verbatim in
every subsequent request.

The OpenAI-compatible gateway stores the raw tool-call dicts (including
``thought_signature``) in ``additional_kwargs["tool_calls"]``, but standard
``langchain_openai.ChatOpenAI`` only serialises the standard fields (``id``,
``type``, ``function``) into the outgoing payload, silently dropping the
signature.  That causes an HTTP 400 ``INVALID_ARGUMENT`` error:

    Unable to submit request because function call `<tool>` in the N. content
    block is missing a `thought_signature`.

This module fixes the problem by overriding ``_get_request_payload`` to
re-inject tool-call signatures back into the outgoing payload for any assistant
message that originally carried them.
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI


class PatchedChatOpenAI(ChatOpenAI):
    """ChatOpenAI with ``thought_signature`` preservation for Gemini thinking via OpenAI gateway.

    When using Gemini with thinking enabled via an OpenAI-compatible gateway,
    the API expects ``thought_signature`` to be present on tool-call objects in
    multi-turn conversations.  This patched version restores those signatures
    from ``AIMessage.additional_kwargs["tool_calls"]`` into the serialised
    request payload before it is sent to the API.

    Usage in ``config.yaml``::

        - name: gemini-2.5-pro-thinking
          display_name: Gemini 2.5 Pro (Thinking)
          use: deerflow.models.patched_openai:PatchedChatOpenAI
          model: google/gemini-2.5-pro-preview
          api_key: $GEMINI_API_KEY
          base_url: https://<your-openai-compat-gateway>/v1
          max_tokens: 16384
          supports_thinking: true
          supports_vision: true
          when_thinking_enabled:
            extra_body:
              thinking:
                type: enabled
    """

    def _get_request_payload(
        self,
        input_: LanguageModelInput,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict:
        """Get request payload with ``thought_signature`` preserved on tool-call objects.

        Overrides the parent method to re-inject ``thought_signature`` fields
        on tool-call objects that were stored in
        ``additional_kwargs["tool_calls"]`` by LangChain but dropped during
        serialisation.
        """
        # Capture the original LangChain messages *before* conversion so we can
        # access fields that the serialiser might drop.
        original_messages = self._convert_input(input_).to_messages()

        # Obtain the base payload from the parent implementation.
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)

        # Sanitize tool schemas: some providers (Gemini via OpenAI-compat) reject
        # array schemas that are missing the required ``items`` field, or that
        # contain non-string enum values (Gemini requires all enum values to be
        # strings, so integer Literal types like Literal[1, 2, 4] must have their
        # enum constraint converted to a description note instead).
        for tool_entry in payload.get("tools", []):
            params = tool_entry.get("function", {}).get("parameters")
            if params:
                _fix_array_schemas(params)
                _fix_integer_enum_schemas(params)

        payload_messages = payload.get("messages", [])

        if len(payload_messages) == len(original_messages):
            for payload_msg, orig_msg in zip(payload_messages, original_messages):
                if payload_msg.get("role") == "assistant" and isinstance(orig_msg, AIMessage):
                    _restore_tool_call_signatures(payload_msg, orig_msg)
        else:
            # Fallback: match assistant-role entries positionally against AIMessages.
            ai_messages = [m for m in original_messages if isinstance(m, AIMessage)]
            assistant_payloads = [(i, m) for i, m in enumerate(payload_messages) if m.get("role") == "assistant"]
            for (_, payload_msg), ai_msg in zip(assistant_payloads, ai_messages):
                _restore_tool_call_signatures(payload_msg, ai_msg)

        return payload


def _restore_tool_call_signatures(payload_msg: dict, orig_msg: AIMessage) -> None:
    """Re-inject ``thought_signature`` onto tool-call objects in *payload_msg*.

    When the Gemini OpenAI-compatible gateway returns a response with function
    calls, each tool-call object may carry a ``thought_signature``.  LangChain
    stores the raw tool-call dicts in ``additional_kwargs["tool_calls"]`` but
    only serialises the standard fields (``id``, ``type``, ``function``) into
    the outgoing payload, silently dropping the signature.

    This function matches raw tool-call entries (by ``id``, falling back to
    positional order) and copies the signature back onto the serialised
    payload entries.
    """
    raw_tool_calls: list[dict] = orig_msg.additional_kwargs.get("tool_calls") or []
    payload_tool_calls: list[dict] = payload_msg.get("tool_calls") or []

    if not raw_tool_calls or not payload_tool_calls:
        return

    # Build an id → raw_tc lookup for efficient matching.
    raw_by_id: dict[str, dict] = {}
    for raw_tc in raw_tool_calls:
        tc_id = raw_tc.get("id")
        if tc_id:
            raw_by_id[tc_id] = raw_tc

    for idx, payload_tc in enumerate(payload_tool_calls):
        # Try matching by id first, then fall back to positional.
        raw_tc = raw_by_id.get(payload_tc.get("id", ""))
        if raw_tc is None and idx < len(raw_tool_calls):
            raw_tc = raw_tool_calls[idx]

        if raw_tc is None:
            continue

        # The gateway may use either snake_case or camelCase.
        sig = raw_tc.get("thought_signature") or raw_tc.get("thoughtSignature")
        if sig:
            payload_tc["thought_signature"] = sig


def _fix_array_schemas(schema: Any) -> None:
    """Recursively ensure every ``"type": "array"`` node has an ``"items"`` field.

    Some providers (e.g. Gemini via OpenAI-compatible gateway) reject tool
    parameter schemas where an array type is missing the ``items`` property.
    This function adds ``"items": {}`` in-place wherever that situation is
    detected, making the schema valid without changing the tool's semantics.
    """
    if not isinstance(schema, dict):
        return

    # Fix the current node if it is an array without items.
    schema_types = schema.get("type")
    if schema_types == "array" or (isinstance(schema_types, list) and "array" in schema_types):
        if "items" not in schema:
            schema["items"] = {"type": "string"}

    # Recursively fix all sub-schemas in every standard location:
    # 1. properties and patternProperties (object sub-schemas)
    for key in ("properties", "patternProperties"):
        for child in (schema.get(key) or {}).values():
            _fix_array_schemas(child)

    # 2. Single schema keys
    for key in ("items", "additionalProperties", "unevaluatedProperties",
                "not", "if", "then", "else", "propertyNames", "contains"):
        child = schema.get(key)
        if child is not None:
            _fix_array_schemas(child)

    # 3. Array of schemas (combinations and variants)
    for key in ("anyOf", "allOf", "oneOf", "prefixItems"):
        for child in (schema.get(key) or []):
            _fix_array_schemas(child)


def _fix_integer_enum_schemas(schema: Any) -> None:
    """Recursively convert non-string enum values to description text.

    Gemini's function-calling API requires all ``enum`` values to be strings.
    Python tools that use ``Literal[1, 2, 4]`` or other integer/number Literal
    types produce ``{"type": "integer", "enum": [1, 2, 4]}`` in their JSON
    schema, which Gemini rejects with ``INVALID_ARGUMENT``.

    This function detects such cases and replaces the ``enum`` list with a
    note appended to the field's ``description``, keeping the original type
    intact so the LLM still returns the correct numeric type.
    """
    if not isinstance(schema, dict):
        return

    # Fix the current node if it has a non-string enum.
    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and any(not isinstance(v, str) for v in enum_values):
        # Build a human-readable list and append to existing description.
        valid_str = ", ".join(str(v) for v in enum_values)
        existing_desc = schema.get("description", "")
        if existing_desc:
            schema["description"] = f"{existing_desc} (valid values: {valid_str})"
        else:
            schema["description"] = f"Valid values: {valid_str}"
        del schema["enum"]

    # Recurse into all standard sub-schema locations.
    for key in ("properties", "patternProperties"):
        for child in (schema.get(key) or {}).values():
            _fix_integer_enum_schemas(child)

    for key in ("items", "additionalProperties", "unevaluatedProperties",
                "not", "if", "then", "else", "propertyNames", "contains"):
        child = schema.get(key)
        if child is not None:
            _fix_integer_enum_schemas(child)

    for key in ("anyOf", "allOf", "oneOf", "prefixItems"):
        for child in (schema.get(key) or []):
            _fix_integer_enum_schemas(child)

