"""Validate a chat-card image choice against the current server catalog."""

from __future__ import annotations

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
