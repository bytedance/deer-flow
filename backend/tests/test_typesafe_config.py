"""Tests for the unified ``typesafe:`` configuration and its two identities.

Design §4: precedence is consumer ``config`` > top-level ``typesafe`` > built-in
defaults; ``mode: off`` resolves nothing at all; and the internal sharing identity
(``sharing_key``) stays separate from each consumer's public policy identity
(``release_policy_parameters``) — behaviour parameters reach only the latter, the
credential fingerprint only the former.
"""

from __future__ import annotations

import hashlib
import json

import httpx
import pytest
import yaml

from deerflow.config.app_config import AppConfig
from deerflow.config.typesafe_config import get_typesafe_config, load_typesafe_config_from_dict, reset_typesafe_config
from deerflow.guardrails.provider import GuardrailRequest
from deerflow.guardrails.typesafe import TypeSafeGuardrailProvider
from deerflow.typesafe.client import TypeSafeClient
from deerflow.typesafe.connection import resolve_connection, resolve_connection_for_mode


@pytest.fixture(autouse=True)
def _isolated_block():
    """The block is a process singleton: keep one test's block out of the next."""
    reset_typesafe_config()
    yield
    reset_typesafe_config()


class _Server:
    """Fake System One endpoint that records every request it receives."""

    def __init__(self, responder=None) -> None:
        self.requests: list[httpx.Request] = []
        self._responder = responder or (lambda request: httpx.Response(200, json={"model": "jev-1.13.0", "answers": {"risky_tool_call": {"type": "noul", "noul": 0.1}}}))

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._responder(request)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def bodies(self) -> list[dict]:
        return [json.loads(request.content) for request in self.requests]


def _tool_call() -> GuardrailRequest:
    return GuardrailRequest(tool_name="bash", tool_input={"command": "ls"})


def _client(**settings) -> TypeSafeClient:
    connection = resolve_connection(settings=settings, configuration_source="tests.typesafe")
    return TypeSafeClient(connection)


# --- precedence ------------------------------------------------------------


class TestPrecedence:
    def test_a_field_only_the_block_sets_reaches_the_request(self, monkeypatch):
        """The block supplies the model and the credential source; the provider sets neither."""
        load_typesafe_config_from_dict({"api_key_env": "SHARED_TYPESAFE_KEY", "model": "block-model", "base_url": "https://block.invalid"})
        monkeypatch.setenv("SHARED_TYPESAFE_KEY", "block-key")
        server = _Server()

        TypeSafeGuardrailProvider(transport_factory=server.transport).evaluate(_tool_call())

        assert server.bodies()[0]["model"] == "block-model"
        assert server.requests[0].headers["authorization"] == "Bearer block-key"

    def test_the_consumers_own_config_wins_over_the_block(self, monkeypatch):
        load_typesafe_config_from_dict({"api_key": "block-key", "model": "block-model", "timeout": 30.0})
        server = _Server()

        TypeSafeGuardrailProvider(api_key="gate-key", model="gate-model", transport_factory=server.transport).evaluate(_tool_call())

        assert server.bodies()[0]["model"] == "gate-model"
        assert server.requests[0].headers["authorization"] == "Bearer gate-key"

    def test_each_field_resolves_independently(self):
        """A consumer overriding one field leaves the block's other values in place."""
        resolved = resolve_connection(
            settings={"api_key": "own-key", "model": "own-model"},
            defaults={"api_key": "block-key", "model": "block-model", "base_url": "https://block.example", "timeout": 9.0, "max_attempts": 4},
            configuration_source="tests.typesafe",
        )

        assert resolved.api_key == "own-key"
        assert resolved.model == "own-model"
        assert resolved.url == "https://block.example/v1/systemone"
        assert (resolved.timeout, resolved.max_attempts) == (9.0, 4)

    def test_the_block_is_optional(self):
        """With no block at all the built-in defaults apply, as before the block existed."""
        resolved = resolve_connection(settings={"api_key": "own-key"}, configuration_source="tests.typesafe")

        assert resolved.url == "https://api.typesafe.ai/v1/systemone"
        assert resolved.api_key_env == "TYPESAFE_API_KEY"

    def test_app_config_parses_the_block_and_feeds_the_singleton(self, tmp_path, monkeypatch):
        """The documented config.yaml shape: a top-level ``typesafe:`` mapping."""
        extensions_path = tmp_path / "extensions_config.json"
        extensions_path.write_text(json.dumps({"mcpServers": {}, "skills": {}}), encoding="utf-8")
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            yaml.safe_dump(
                {
                    "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
                    "typesafe": {"api_key_env": "SHARED_TYPESAFE_KEY", "model": "block-model", "timeout": 30.0},
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))

        block = AppConfig.from_file(str(config_path)).typesafe
        # AppConfig loading publishes this block to the process singleton; the
        # provider reads it when its own config leaves a field unset.
        load_typesafe_config_from_dict(block.model_dump())

        assert block.connection_defaults() == {"api_key_env": "SHARED_TYPESAFE_KEY", "model": "block-model", "timeout": 30.0}
        assert get_typesafe_config().connection_defaults() == block.connection_defaults()

    def test_an_unset_field_is_not_a_configured_field(self):
        """``None`` means "not configured", so the next source still applies."""
        resolved = resolve_connection(settings={"api_key": "own-key", "model": None}, defaults={"model": "block-model"}, configuration_source="tests.typesafe")

        assert resolved.model == "block-model"


# --- mode: off -------------------------------------------------------------


class TestModeOff:
    def test_mode_off_resolves_no_credentials_and_no_class_path(self, monkeypatch):
        monkeypatch.delenv("MISSING_TYPESAFE_KEY", raising=False)
        consumer_config = {"mode": "off", "use": "not.a.real.module:Cls", "base_url": "https://block.invalid", "api_key_env": "MISSING_TYPESAFE_KEY"}

        resolved = resolve_connection_for_mode(mode="off", settings=consumer_config, defaults=None, configuration_source="memory.prescreen.config")

        assert resolved is None, "an off consumer resolves nothing, constructs nothing and sends nothing"

    def test_mode_off_needs_no_configuration_at_all(self):
        assert resolve_connection_for_mode(mode="off", settings=None, defaults=None, configuration_source="memory.prescreen.config") is None

    def test_an_enabled_mode_still_fails_loudly(self, monkeypatch):
        """Teeth: ``off`` is what suppressed the failure, not a lenient resolver."""
        monkeypatch.delenv("MISSING_TYPESAFE_KEY", raising=False)
        consumer_config = {"mode": "shadow", "api_key_env": "MISSING_TYPESAFE_KEY"}

        with pytest.raises(ValueError) as excinfo:
            resolve_connection_for_mode(mode="shadow", settings=consumer_config, defaults=None, configuration_source="memory.prescreen.config")

        assert "MISSING_TYPESAFE_KEY" in str(excinfo.value)
        assert "memory.prescreen.config" in str(excinfo.value)


# --- the two identities ----------------------------------------------------


class TestIdentities:
    def test_the_sharing_key_tracks_every_sharing_dimension(self):
        base = {"api_key": "key-a", "model": "jev-latest"}
        baseline = _client(**base).sharing_key(max_state_chars=100)

        assert _client(**base).sharing_key(max_state_chars=100) == baseline, "the same settings share"
        assert _client(api_key="key-b", model="jev-latest").sharing_key(max_state_chars=100) != baseline, "a different credential is a different request"
        assert _client(api_key="key-a", model="jev-other").sharing_key(max_state_chars=100) != baseline, "a different model is a different request"
        assert _client(**base).sharing_key(max_state_chars=200) != baseline, "a different input limit is a different request"

    def test_a_different_transport_factory_never_shares(self):
        connection = resolve_connection(settings={"api_key": "key-a"}, configuration_source="tests.typesafe")
        first = TypeSafeClient(connection, transport_factory=_Server().transport)
        second = TypeSafeClient(connection, transport_factory=_Server().transport)

        assert first.sharing_key() != second.sharing_key()

    def test_the_sharing_key_never_carries_the_credential_itself(self):
        key = _client(api_key="key-a").sharing_key()

        assert "key-a" not in key

    def test_the_policy_identity_carries_behaviour_but_no_credential(self):
        declared = TypeSafeGuardrailProvider(api_key="key-a", threshold=0.25, tools=["bash"]).release_policy_parameters()
        serialized = json.dumps(declared)

        assert declared["threshold"] == 0.25
        assert declared["tools"] == ["bash"]
        assert "key-a" not in serialized
        assert hashlib.sha256(b"key-a").hexdigest()[:16] not in serialized, "the credential fingerprint is internal to sharing_key"
