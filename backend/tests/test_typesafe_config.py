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
from pydantic import ValidationError

from deerflow.config.app_config import AppConfig
from deerflow.config.typesafe_config import TypeSafeConfig, get_typesafe_config, load_typesafe_config_from_dict, reset_typesafe_config
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

    def test_a_consumers_api_key_env_is_not_overridden_by_the_blocks_literal_key(self, monkeypatch):
        """One credential source per layer: the consumer's own variable decides, and
        everything else still comes from the block.

        The block's literal key would otherwise win — and it may not be valid for the
        consumer's endpoint at all — while ``connection.api_key_env`` kept naming the
        variable the consumer configured.
        """
        load_typesafe_config_from_dict({"api_key": "block-literal-key", "model": "block-model"})
        monkeypatch.setenv("GATE_ONLY_KEY", "gate-env-key")
        server = _Server()

        TypeSafeGuardrailProvider(api_key_env="GATE_ONLY_KEY", transport_factory=server.transport).evaluate(_tool_call())

        assert server.requests[0].headers["authorization"] == "Bearer gate-env-key"
        assert server.bodies()[0]["model"] == "block-model"

    def test_inside_one_layer_a_literal_key_beats_that_layers_env_name(self, monkeypatch):
        """The standalone semantics are kept: a layer that sets both uses its literal key."""
        monkeypatch.setenv("IGNORED_KEY", "env-key")
        server = _Server()

        TypeSafeGuardrailProvider(api_key="literal-key", api_key_env="IGNORED_KEY", transport_factory=server.transport).evaluate(_tool_call())

        assert server.requests[0].headers["authorization"] == "Bearer literal-key"


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


# --- values no request could use fail where they are configured ------------


class TestConnectionValuesFailAtConstruction:
    """A connection value that no request can use must fail at construction, not per call.

    ``base_url`` used to be checked only for being non-blank and the credential only
    for being non-empty, so ``ftp://…``, a base URL with a query string, and a key
    mounted from a file with a trailing newline all built fine and then failed on
    every request — the last one by putting the whole ``Bearer`` value into h11's
    ``LocalProtocolError`` message.
    """

    @pytest.mark.parametrize(
        "base_url",
        [
            "ftp://api.typesafe.ai",
            "api.typesafe.ai",
            "https://",
            "https://api.typesafe.ai?tenant=1",
            "https://api.typesafe.ai#frag",
            "https://user:pass@api.typesafe.ai",
            "https://api.typesafe.ai\n",
            "https://api.typesafe.ai:notaport",
        ],
    )
    def test_a_base_url_no_request_could_use_is_refused(self, base_url):
        with pytest.raises(ValueError, match="base_url"):
            resolve_connection(settings={"api_key": "own-key", "base_url": base_url}, configuration_source="tests.typesafe")

    def test_a_usable_base_url_still_resolves_with_its_path_prefix(self):
        resolved = resolve_connection(settings={"api_key": "own-key", "base_url": "http://127.0.0.1:8080/prefix"}, configuration_source="tests.typesafe")

        assert resolved.url == "http://127.0.0.1:8080/prefix/v1/systemone"

    @pytest.mark.parametrize("api_key", ["sk-live-abc\n", "sk-live-abc ", " sk-live-abc", "sk-live-abc\t", "sk-live-abc\u00a0"])
    def test_a_credential_that_cannot_be_a_header_value_is_refused_without_echoing_it(self, api_key):
        with pytest.raises(ValueError) as excinfo:
            resolve_connection(settings={"api_key": api_key}, configuration_source="tests.typesafe")

        assert api_key not in str(excinfo.value), "the value is never echoed"
        assert "api_key" in str(excinfo.value), "the message names the setting to fix"

    def test_a_credential_read_from_the_environment_is_checked_the_same_way(self, monkeypatch):
        """The realistic shape: a secret mounted from a file ends with a newline."""
        monkeypatch.setenv("MOUNTED_TYPESAFE_KEY", "sk-live-mount\n")

        with pytest.raises(ValueError) as excinfo:
            resolve_connection(settings={"api_key_env": "MOUNTED_TYPESAFE_KEY"}, configuration_source="tests.typesafe")

        assert "sk-live-mount" not in str(excinfo.value)


class TestStrictBlockValues:
    """The block's values are checked like the consumer ``config`` path's.

    In pydantic's lax mode ``max_attempts: true`` silently became ``1`` (``bool`` is
    an ``int``) while the same value under ``guardrails.provider.config`` was
    rejected, so one retry count meant two different things depending on where it was
    written.
    """

    def test_a_boolean_retry_count_is_rejected(self):
        with pytest.raises(ValidationError):
            TypeSafeConfig.model_validate({"max_attempts": True})

    def test_a_boolean_timeout_is_rejected(self):
        with pytest.raises(ValidationError):
            TypeSafeConfig.model_validate({"timeout": True})

    def test_an_integer_is_still_a_usable_float(self):
        block = TypeSafeConfig.model_validate({"timeout": 5, "max_attempts": 2})

        assert block.connection_defaults() == {"timeout": 5.0, "max_attempts": 2}

    def test_a_config_file_with_a_boolean_retry_count_is_refused(self, tmp_path, monkeypatch):
        """The operator sees a config error instead of a silently shortened budget."""
        extensions_path = tmp_path / "extensions_config.json"
        extensions_path.write_text(json.dumps({"mcpServers": {}, "skills": {}}), encoding="utf-8")
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            yaml.safe_dump(
                {
                    "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
                    "typesafe": {"api_key_env": "SHARED_TYPESAFE_KEY", "max_attempts": True},
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))

        with pytest.raises(ValidationError):
            AppConfig.from_file(str(config_path))
