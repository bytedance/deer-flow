"""Validate a chat-card image choice against the current server catalog."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from langchain_core.messages import HumanMessage, ToolMessage

from deerflow.agents.human_input import read_human_input_response
from deerflow.config.image_generation import ManagedImageGenerationProfileStore, legacy_image_model_identity


def selected_image_source_from_reply(
    graph_input: dict[str, Any],
    prior_messages: tuple[Any, ...],
    environment: dict[str, str],
) -> Literal["managed", "sandbox_environment"] | None:
    """Accept only a choice from the latest server-recorded image-model card."""
    incoming = graph_input.get("messages") if isinstance(graph_input, dict) else None
    if not isinstance(incoming, (list, tuple)) or not incoming:
        return None
    message = incoming[-1]
    if not isinstance(message, HumanMessage):
        return None
    response = read_human_input_response(message.additional_kwargs)
    if response is None or response["source"] != "ask_clarification" or response["response_kind"] != "option":
        return None

    latest_card = next((item for item in reversed(prior_messages) if isinstance(item, ToolMessage) and item.name == "ask_clarification"), None)
    if latest_card is None or latest_card.id != response["request_id"]:
        return None
    artifact = latest_card.artifact if isinstance(latest_card.artifact, dict) else {}
    payload = artifact.get("human_input")
    if not isinstance(payload, dict) or payload.get("clarification_type") != "image_model_choice":
        return None
    marker = payload.get("image_profile_choice")
    options = payload.get("options")
    if not isinstance(marker, dict) or not isinstance(options, list):
        return None
    option = next((item for item in options if isinstance(item, dict) and item.get("id") == response["option_id"]), None)
    if option is None or option.get("value") != response["value"]:
        return None

    managed = [item for item in ManagedImageGenerationProfileStore().list() if item.enabled]
    if len(managed) != 1 or managed[0].revision != marker.get("managed_revision"):
        return None
    if legacy_image_model_identity(environment) != marker.get("server_model"):
        return None
    if response["option_id"] == "option-1":
        return "managed"
    if response["option_id"] == "option-2":
        return "sandbox_environment"
    return None


def adapt_channel_image_choice_reply(
    graph_input: dict[str, Any],
    prior_messages: tuple[Any, ...],
    environment: dict[str, str],
    context: Mapping[str, Any],
) -> tuple[dict[str, Any], Literal["managed", "sandbox_environment"] | None]:
    """Convert an explicit IM answer to the current server-recorded image choice.

    The channel supplies only text. The card, its owner and its option values
    come from the checkpoint; the existing selector rechecks the managed revision
    and server model identity.
    """
    channel_name = context.get("channel_name")
    channel_user_id = context.get("channel_user_id")
    if not isinstance(channel_name, str) or not channel_name or not isinstance(channel_user_id, str) or not channel_user_id:
        return graph_input, None

    incoming = graph_input.get("messages") if isinstance(graph_input, dict) else None
    if not isinstance(incoming, list) or len(incoming) != 1 or not isinstance(incoming[0], HumanMessage):
        return graph_input, None
    message = incoming[0]
    if not isinstance(message.content, str) or message.additional_kwargs:
        return graph_input, None

    # The card must still be the last checkpointed message. A later turn or
    # another clarification makes a number in ordinary chat just a number.
    card = prior_messages[-1] if prior_messages else None
    if not isinstance(card, ToolMessage) or card.name != "ask_clarification" or not card.id:
        return graph_input, None
    artifact = card.artifact if isinstance(card.artifact, dict) else {}
    payload = artifact.get("human_input")
    if not isinstance(payload, dict) or payload.get("request_id") != card.id or payload.get("clarification_type") != "image_model_choice" or payload.get("input_mode") != "single_choice":
        return graph_input, None
    marker = payload.get("image_profile_choice")
    if not isinstance(marker, dict) or marker.get("channel_name") != channel_name or marker.get("channel_user_id") != channel_user_id:
        return graph_input, None
    options = payload.get("options")
    if not isinstance(options, list) or len(options) != 2:
        return graph_input, None

    answer = message.content.strip()
    matched = []
    for index, option in enumerate(options, 1):
        if not isinstance(option, dict) or option.get("id") != f"option-{index}":
            return graph_input, None
        value = option.get("value")
        if not isinstance(value, str) or not value:
            return graph_input, None
        if answer == str(index) or answer == value:
            matched.append(option)
    if len(matched) != 1:
        return graph_input, None
    option = matched[0]
    response = {
        "version": 1,
        "kind": "human_input_response",
        "source": "ask_clarification",
        "request_id": card.id,
        "response_kind": "option",
        "option_id": option["id"],
        "value": option["value"],
    }
    adapted_message = message.model_copy(
        update={
            "content": option["value"],
            "additional_kwargs": {**message.additional_kwargs, "hide_from_ui": True, "human_input_response": response},
        }
    )
    adapted = {**graph_input, "messages": [adapted_message]}
    source = selected_image_source_from_reply(adapted, prior_messages, environment)
    return (adapted, source) if source is not None else (graph_input, None)
