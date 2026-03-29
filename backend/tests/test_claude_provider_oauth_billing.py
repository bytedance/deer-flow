"""Tests for ClaudeChatModel._apply_oauth_billing."""

import json

import pytest

from deerflow.models.claude_provider import OAUTH_BILLING_HEADER, ClaudeChatModel


def _make_model() -> ClaudeChatModel:
    """Return a minimal ClaudeChatModel instance in OAuth mode without network calls."""
    import unittest.mock as mock

    with mock.patch.object(ClaudeChatModel, "model_post_init"):
        m = ClaudeChatModel(model="claude-sonnet-4-6", anthropic_api_key="sk-ant-oat-fake-token")  # type: ignore[call-arg]
    m._is_oauth = True
    m._oauth_access_token = "sk-ant-oat-fake-token"
    return m


@pytest.fixture()
def model() -> ClaudeChatModel:
    return _make_model()


def _billing_block() -> dict:
    return {"type": "text", "text": OAUTH_BILLING_HEADER}


# ---------------------------------------------------------------------------
# Billing block injection
# ---------------------------------------------------------------------------


def test_billing_injected_first_when_no_system(model):
    payload: dict = {}
    model._apply_oauth_billing(payload)
    assert payload["system"][0] == _billing_block()


def test_billing_injected_first_into_list(model):
    payload = {"system": [{"type": "text", "text": "You are a helpful assistant."}]}
    model._apply_oauth_billing(payload)
    assert payload["system"][0] == _billing_block()
    assert payload["system"][1]["text"] == "You are a helpful assistant."


def test_billing_injected_first_into_string_system(model):
    payload = {"system": "You are helpful."}
    model._apply_oauth_billing(payload)
    assert payload["system"][0] == _billing_block()
    assert payload["system"][1]["text"] == "You are helpful."


def test_billing_not_duplicated_on_second_call(model):
    payload = {"system": [{"type": "text", "text": "prompt"}]}
    model._apply_oauth_billing(payload)
    model._apply_oauth_billing(payload)
    billing_count = sum(1 for b in payload["system"] if isinstance(b, dict) and OAUTH_BILLING_HEADER in b.get("text", ""))
    assert billing_count == 1


def test_billing_moved_to_first_if_not_already_first(model):
    """Billing block already present but not first — must be normalized to index 0."""
    payload = {
        "system": [
            {"type": "text", "text": "other block"},
            _billing_block(),
        ]
    }
    model._apply_oauth_billing(payload)
    assert payload["system"][0] == _billing_block()
    assert len([b for b in payload["system"] if OAUTH_BILLING_HEADER in b.get("text", "")]) == 1


def test_billing_string_with_header_collapsed_to_single_block(model):
    """If system is a string that already contains the billing header, collapse to one block."""
    payload = {"system": OAUTH_BILLING_HEADER}
    model._apply_oauth_billing(payload)
    assert payload["system"] == [_billing_block()]


# ---------------------------------------------------------------------------
# metadata.user_id
# ---------------------------------------------------------------------------


def test_metadata_user_id_added_when_missing(model):
    payload: dict = {}
    model._apply_oauth_billing(payload)
    assert "metadata" in payload
    user_id = json.loads(payload["metadata"]["user_id"])
    assert "device_id" in user_id
    assert "session_id" in user_id
    assert user_id["account_uuid"] == "deerflow"


def test_metadata_user_id_not_overwritten_if_present(model):
    payload = {"metadata": {"user_id": "existing-value"}}
    model._apply_oauth_billing(payload)
    assert payload["metadata"]["user_id"] == "existing-value"


def test_metadata_non_dict_replaced_with_dict(model):
    """Non-dict metadata (e.g. None or a string) should be replaced, not crash."""
    for bad_value in (None, "string-metadata", 42):
        payload = {"metadata": bad_value}
        model._apply_oauth_billing(payload)
        assert isinstance(payload["metadata"], dict)
        assert "user_id" in payload["metadata"]
