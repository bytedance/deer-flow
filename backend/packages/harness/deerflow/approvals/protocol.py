"""Shared approval batching and resume normalization, including legacy pauses."""

from collections.abc import Mapping


def approval_responses(resume):
    if not isinstance(resume, Mapping):
        return None
    responses = resume.get("responses")
    if isinstance(responses, list):
        return responses
    groups = list(resume.values())
    if groups and all(isinstance(value, Mapping) and isinstance(value.get("responses"), list) for value in groups):
        return [response for value in groups for response in value["responses"]]
    return None


def combine_approval_payloads(payloads):
    if not payloads:
        return None
    first = payloads[0]
    if len(payloads) == 1:
        return first
    allowed = first.get("allowed_decisions", ["approve", "reject"])
    return {
        **first,
        "actions": [action for payload in payloads for action in payload.get("actions", [])],
        "pending_tool_call_ids": [call_id for payload in payloads for call_id in payload.get("pending_tool_call_ids", [])],
        "allowed_decisions": [decision for decision in allowed if all(decision in payload.get("allowed_decisions", []) for payload in payloads)],
    }
