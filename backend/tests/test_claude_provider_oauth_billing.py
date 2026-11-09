"""Tests for ClaudeChatModel._apply_oauth_billing."""

import asyncio
import json
from unittest import mock

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


def test_sync_create_strips_cache_control_from_oauth_payload(model):
    payload = {
        "system": [{"type": "text", "text": "sys", "cache_control": {"type": "ephemeral"}}],
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": "hi", "cache_control": {"type": "ephemeral"}}],
            }
        ],
        "tools": [{"name": "demo", "input_schema": {"type": "object"}, "cache_control": {"type": "ephemeral"}}],
    }

    with mock.patch.object(model._client.messages, "create", return_value=object()) as create:
        model._create(payload)

    sent_payload = create.call_args.kwargs
    assert "cache_control" not in sent_payload["system"][0]
    assert "cache_control" not in sent_payload["messages"][0]["content"][0]
    assert "cache_control" not in sent_payload["tools"][0]


def test_async_create_strips_cache_control_from_oauth_payload(model):
    payload = {
        "system": [{"type": "text", "text": "sys", "cache_control": {"type": "ephemeral"}}],
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": "hi", "cache_control": {"type": "ephemeral"}}],
            }
        ],
        "tools": [{"name": "demo", "input_schema": {"type": "object"}, "cache_control": {"type": "ephemeral"}}],
    }

    with mock.patch.object(model._async_client.messages, "create", new=mock.AsyncMock(return_value=object())) as create:
        asyncio.run(model._acreate(payload))

    sent_payload = create.call_args.kwargs
    assert "cache_control" not in sent_payload["system"][0]
    assert "cache_control" not in sent_payload["messages"][0]["content"][0]
    assert "cache_control" not in sent_payload["tools"][0]


# ---------------------------------------------------------------------------
# OAuth beta merging (issue #8060)
# ---------------------------------------------------------------------------


def _oauth_betas() -> list[str]:
    from deerflow.models.credential_loader import OAUTH_ANTHROPIC_BETAS

    return OAUTH_ANTHROPIC_BETAS.split(",")


def test_request_betas_merge_oauth_betas(model):
    payload: dict = {"betas": ["context-1m-2025-08-07"]}
    model._merge_oauth_betas(payload)
    assert payload["betas"] == [*_oauth_betas(), "context-1m-2025-08-07"]


def test_empty_request_betas_still_carries_oauth_betas(model):
    payload: dict = {"betas": []}
    model._merge_oauth_betas(payload)
    assert payload["betas"] == _oauth_betas()


def test_missing_request_betas_leaves_payload_untouched(model):
    """Without per-request betas the payload stays untouched, so langchain-anthropic
    keeps the client default header path (_client.messages.create) instead of
    switching to _client.beta.messages.create with an equivalent header."""
    payload: dict = {}
    model._merge_oauth_betas(payload)
    assert "betas" not in payload


def test_request_already_carrying_an_oauth_beta_is_not_duplicated(model):
    payload: dict = {"betas": ["oauth-2025-04-20"]}
    model._merge_oauth_betas(payload)
    assert payload["betas"].count("oauth-2025-04-20") == 1
    assert set(_oauth_betas()) <= set(payload["betas"])


def test_api_key_model_never_merges_oauth_betas():
    """_get_request_payload only merges betas in the OAuth branch: an API-key
    model's configured betas pass through untouched."""
    from unittest.mock import MagicMock, patch

    from langchain_core.messages import HumanMessage

    with patch.object(ClaudeChatModel, "model_post_init"):
        m = ClaudeChatModel(model="claude-sonnet-4-6", anthropic_api_key="sk-ant-api03-real-key")  # type: ignore[call-arg]
    m._is_oauth = False
    m._merge_oauth_betas = MagicMock()

    payload = m._get_request_payload([HumanMessage(content="hi")])
    m._merge_oauth_betas.assert_not_called()
    assert payload.get("betas") is None


def test_request_payload_merges_betas_on_oauth_path():
    """_get_request_payload itself must merge OAuth betas when the request
    carries per-request betas, so the tests catch a regression in the
    request path (not just errors inside the helper)."""
    from langchain_core.messages import HumanMessage

    m = _make_model()
    payload = m._get_request_payload([HumanMessage(content="hi")], betas=["context-1m-2025-08-07"])
    assert payload["betas"] == [*_oauth_betas(), "context-1m-2025-08-07"]


def test_request_payload_without_betas_stays_on_default_path():
    """_get_request_payload must not introduce betas when the request carries
    none: the payload stays untouched so langchain-anthropic keeps the client
    default header path."""
    from langchain_core.messages import HumanMessage

    m = _make_model()
    payload = m._get_request_payload([HumanMessage(content="hi")])
    assert "betas" not in payload


def test_request_payload_merges_extra_headers_beta():
    """An anthropic-beta in extra_headers replaces both the client default and
    the betas header, so it needs the same OAuth merge (case-insensitive key)."""
    from langchain_core.messages import HumanMessage

    m = _make_model()
    payload = m._get_request_payload([HumanMessage(content="hi")], extra_headers={"Anthropic-Beta": "context-1m-2025-08-07"})
    assert payload["extra_headers"]["Anthropic-Beta"] == ",".join([*_oauth_betas(), "context-1m-2025-08-07"])


def test_extra_headers_without_beta_header_are_untouched():
    from langchain_core.messages import HumanMessage

    m = _make_model()
    payload = m._get_request_payload([HumanMessage(content="hi")], extra_headers={"x-custom": "1"})
    assert payload["extra_headers"] == {"x-custom": "1"}
