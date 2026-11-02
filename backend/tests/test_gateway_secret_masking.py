"""Shared credential masking used by the MCP and memory config routes."""

import pytest

from app.gateway.secret_masking import MASKED_VALUE, mask_secret_values, normalize_config_key


@pytest.mark.parametrize(
    ("key", "normalized"),
    [("api_key", "api_key"), ("apiKey", "api_key"), ("APIKey", "api_key"), ("API-Key", "api_key"), ("accessToken", "access_token"), ("X-Api-Key", "x_api_key")],
)
def test_normalize_config_key_snake_cases_spellings(key: str, normalized: str) -> None:
    assert normalize_config_key(key) == normalized


def _is_secret(key: str) -> bool:
    return key in {"api_key", "credentials"}


def test_mask_secret_values_masks_at_any_depth_without_mutating() -> None:
    value = {"api_key": "sk-top", "nested": {"api_key": "sk-nested", "model": "m"}, "items": [{"api_key": "sk-list"}, "plain"], "credentials": {"client_id": "id", "client_secret": "s"}}

    masked = mask_secret_values(value, _is_secret)

    assert masked == {"api_key": MASKED_VALUE, "nested": {"api_key": MASKED_VALUE, "model": "m"}, "items": [{"api_key": MASKED_VALUE}, "plain"], "credentials": MASKED_VALUE}
    assert value["nested"]["api_key"] == "sk-nested"


@pytest.mark.parametrize(("keep_unset", "expected"), [(False, {"api_key": MASKED_VALUE, "credentials": MASKED_VALUE}), (True, {"api_key": None, "credentials": ""})])
def test_mask_secret_values_keeps_unset_values_only_when_asked(keep_unset: bool, expected: dict) -> None:
    assert mask_secret_values({"api_key": None, "credentials": ""}, _is_secret, keep_unset=keep_unset) == expected
