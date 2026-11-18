# SPDX-License-Identifier: MIT
"""Numeric config fields that previously accepted silently-broken values.

Each guarded field used to admit zero, negatives, or booleans (YAML/JSON
``true`` coerces to ``1``) and only failed later at runtime — or worse, kept
running with a nonsense value. Bounds and the boolean rejection mirror the
guards already shipped for ``stream_bridge_config`` (heartbeat interval) and
``database_config`` (pool settings).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from deerflow.config.app_config import CircuitBreakerConfig
from deerflow.config.extensions_config import McpOAuthConfig, McpServerConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.run_events_config import RunEventsConfig
from deerflow.config.sandbox_config import SandboxConfig, SandboxOwnershipConfig
from deerflow.config.summarization_config import SummarizationConfig


class TestCircuitBreakerGuards:
    def test_defaults_pass(self) -> None:
        config = CircuitBreakerConfig()
        assert config.failure_threshold == 5
        assert config.recovery_timeout_sec == 60

    @pytest.mark.parametrize("field", ["failure_threshold", "recovery_timeout_sec"])
    @pytest.mark.parametrize("bad", [0, -1, True])
    def test_rejects_non_positive_and_boolean(self, field: str, bad: int | bool) -> None:
        with pytest.raises(ValidationError):
            CircuitBreakerConfig(**{field: bad})


class TestMcpTimeoutGuards:
    def test_defaults_pass(self) -> None:
        config = McpServerConfig()
        assert config.tool_call_timeout is None
        assert config.session_init_timeout is not None

    @pytest.mark.parametrize("field", ["tool_call_timeout", "session_init_timeout"])
    @pytest.mark.parametrize("bad", [0, -1.0, True])
    def test_rejects_non_positive_and_boolean(self, field: str, bad: float | bool) -> None:
        with pytest.raises(ValidationError):
            McpServerConfig(**{field: bad})

    def test_zero_point_five_and_none_are_valid(self) -> None:
        config = McpServerConfig(tool_call_timeout=0.5, session_init_timeout=None)
        assert config.tool_call_timeout == 0.5
        assert config.session_init_timeout is None

    @pytest.mark.parametrize("bad", [-1, True])
    def test_refresh_skew_rejects_negative_and_boolean(self, bad: int | bool) -> None:
        with pytest.raises(ValidationError):
            McpOAuthConfig(token_url="https://sso.example.org/token", refresh_skew_seconds=bad)


class TestStreamChunkTimeoutGuard:
    def test_none_default_passes(self) -> None:
        config = ModelConfig(name="m", use="default", model="gpt-x", stream_chunk_timeout=None)
        assert config.stream_chunk_timeout is None

    @pytest.mark.parametrize("bad", [0, -1.0, True])
    def test_rejects_non_positive_and_boolean(self, bad: float | bool) -> None:
        with pytest.raises(ValidationError):
            ModelConfig(name="m", use="default", model="gpt-x", stream_chunk_timeout=bad)


class TestMaxTraceContentGuard:
    def test_default_passes(self) -> None:
        assert RunEventsConfig().max_trace_content == 10240

    @pytest.mark.parametrize("bad", [0, -1, True])
    def test_rejects_non_positive_and_boolean(self, bad: int | bool) -> None:
        with pytest.raises(ValidationError):
            RunEventsConfig(**{"max_trace_content": bad})


class TestSandboxPortAndIdleTimeoutGuards:
    def test_unset_defaults_pass(self) -> None:
        config = SandboxConfig(use="local")
        assert config.port is None
        assert config.idle_timeout is None

    def test_zero_idle_timeout_is_documented_valid(self) -> None:
        assert SandboxConfig(use="local", idle_timeout=0).idle_timeout == 0

    @pytest.mark.parametrize("bad", [0, 65536, -1, True])
    def test_port_rejects_out_of_range_and_boolean(self, bad: int | bool) -> None:
        with pytest.raises(ValidationError):
            SandboxConfig(use="local", port=bad)

    @pytest.mark.parametrize("bad", [-1, True])
    def test_idle_timeout_rejects_negative_and_boolean(self, bad: int | bool) -> None:
        with pytest.raises(ValidationError):
            SandboxConfig(use="local", idle_timeout=bad)


class TestSiblingBoolRejection:
    """Same-class siblings with bounds but no boolean rejection, flagged in review."""

    def test_sandbox_numeric_fields_reject_booleans(self) -> None:
        with pytest.raises(ValidationError):
            SandboxConfig(use="local", replicas=True)
        with pytest.raises(ValidationError):
            SandboxConfig(use="local", acquire_timeout=True)
        with pytest.raises(ValidationError):
            SandboxConfig(use="local", burst_limit=True)
        with pytest.raises(ValidationError):
            SandboxConfig(use="local", health_check_skip_seconds=True)
        with pytest.raises(ValidationError):
            SandboxConfig(use="local", bash_output_max_chars=True)
        with pytest.raises(ValidationError):
            SandboxConfig(use="local", read_file_output_max_chars=True)
        with pytest.raises(ValidationError):
            SandboxConfig(use="local", ls_output_max_chars=True)
        with pytest.raises(ValidationError):
            SandboxConfig(use="local", bash_command_timeout=True)
        with pytest.raises(ValidationError):
            SandboxOwnershipConfig(renewal_interval_seconds=True)
        with pytest.raises(ValidationError):
            SandboxOwnershipConfig(ttl_multiplier=True)

    def test_ownership_defaults_still_pass(self) -> None:
        config = SandboxOwnershipConfig()
        assert config.renewal_interval_seconds == 30.0
        assert config.ttl_multiplier == 4.0

    def test_context_window_rejects_booleans_and_nonpositive(self) -> None:
        with pytest.raises(ValidationError):
            ModelConfig(name="m", use="default", model="gpt-x", context_window=True)
        with pytest.raises(ValidationError):
            ModelConfig(name="m", use="default", model="gpt-x", context_window=0)
        with pytest.raises(ValidationError):
            ModelConfig(name="m", use="default", model="gpt-x", context_window=-1)

    def test_allow_inf_nan_rejection(self) -> None:
        with pytest.raises(ValidationError):
            McpServerConfig(tool_call_timeout=float("inf"))
        with pytest.raises(ValidationError):
            ModelConfig(name="m", use="default", model="gpt-x", stream_chunk_timeout=float("inf"))
        with pytest.raises(ValidationError):
            ModelConfig(name="m", use="default", model="gpt-x", stream_chunk_timeout=float("nan"))

    def test_refresh_skew_zero_is_a_valid_boundary(self) -> None:
        config = McpOAuthConfig(token_url="https://sso.example.org/token", refresh_skew_seconds=0)
        assert config.refresh_skew_seconds == 0


class TestTrimTokensToSummarizeGuard:
    def test_default_and_none_pass(self) -> None:
        assert SummarizationConfig().trim_tokens_to_summarize == 4000
        assert SummarizationConfig(trim_tokens_to_summarize=None).trim_tokens_to_summarize is None

    @pytest.mark.parametrize("bad", [0, -1, True])
    def test_rejects_non_positive_and_boolean(self, bad: int | bool) -> None:
        with pytest.raises(ValidationError):
            SummarizationConfig(**{"trim_tokens_to_summarize": bad})
