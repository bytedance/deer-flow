"""Numeric bounds and YAML boolean-coercion rejection guards across configuration models."""

from typing import cast

import pytest
from pydantic import ValidationError, ValidationInfo

from deerflow.config._boolean_guards import reject_boolean
from deerflow.config.acp_config import ACPAgentConfig
from deerflow.config.app_config import AppConfig, CircuitBreakerConfig, LlmCallConfig
from deerflow.config.extensions_config import McpOAuthConfig, McpServerConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.run_events_config import RunEventsConfig
from deerflow.config.sandbox_config import SandboxConfig, SandboxOwnershipConfig
from deerflow.config.scheduler_config import SchedulerConfig
from deerflow.config.subagents_config import CustomSubagentConfig, SubagentOverrideConfig, SubagentsAppConfig
from deerflow.config.summarization_config import SummarizationConfig

# --- test_boolean_guards ---


class _Probe:
    """Minimal harness so ``info.field_name`` resolves like a real field."""

    def __init__(self, field_name: str) -> None:
        self.field_name = field_name


def _info(field_name: str) -> ValidationInfo:
    return cast(ValidationInfo, _Probe(field_name))


def test_reject_boolean_names_the_field() -> None:
    with pytest.raises(ValueError, match="recursion_limit must be an integer, not a boolean"):
        reject_boolean(True, _info("recursion_limit"), kind="an integer")


def test_reject_boolean_passes_numbers_through() -> None:
    assert reject_boolean(0, _info("hard_limit"), kind="an integer") == 0
    assert reject_boolean(2.5, _info("interval"), kind="a number") == 2.5


def test_reject_boolean_custom_kind_wording() -> None:
    with pytest.raises(ValueError, match="command_timeout must be a number of seconds or null, not a boolean"):
        reject_boolean(True, _info("command_timeout"), kind="a number of seconds or null")


# --- test_app_config_boolean_thresholds ---

LLM_CALL_INT_FIELDS = (
    "max_concurrent_calls",
    "retry_max_attempts",
    "retry_base_delay_ms",
    "retry_cap_delay_ms",
    "burst_retry_base_delay_ms",
)


def _app_config(**overrides: object) -> AppConfig:
    return AppConfig(sandbox=SandboxConfig(use="local"), **overrides)


@pytest.mark.parametrize("value", [True, False])
@pytest.mark.parametrize("field", LLM_CALL_INT_FIELDS)
def test_llm_call_config_rejects_boolean_integers(field: str, value: bool) -> None:
    with pytest.raises(ValidationError, match="must be an integer, not a boolean"):
        LlmCallConfig(**{field: value})


def test_llm_call_config_keeps_numeric_inputs() -> None:
    config = LlmCallConfig(max_concurrent_calls="4", retry_max_attempts=3)
    assert config.max_concurrent_calls == 4
    assert config.retry_max_attempts == 3


@pytest.mark.parametrize("value", [True, False])
@pytest.mark.parametrize("field", ["recursion_limit", "max_recursion_limit"])
def test_recursion_limits_reject_booleans(field: str, value: bool) -> None:
    with pytest.raises(ValidationError, match="must be an integer, not a boolean"):
        _app_config(**{field: value})


def test_recursion_limits_keep_numeric_inputs() -> None:
    config = _app_config(recursion_limit="25")
    assert config.recursion_limit == 25


# --- test_scheduler_config_boolean_integers ---

SCHEDULER_INT_FIELDS = (
    "poll_interval_seconds",
    "lease_seconds",
    "max_concurrent_runs",
    "max_concurrent_runs_per_user",
    "queue_timeout_seconds",
    "min_once_delay_seconds",
    "recursion_limit",
)


@pytest.mark.parametrize("value", [True, False])
@pytest.mark.parametrize("field", SCHEDULER_INT_FIELDS)
def test_scheduler_config_rejects_boolean_integers(field: str, value: bool) -> None:
    with pytest.raises(ValidationError, match="must be an integer, not a boolean"):
        SchedulerConfig(**{field: value})


def test_scheduler_config_keeps_numeric_inputs() -> None:
    config = SchedulerConfig(
        poll_interval_seconds="30",
        max_concurrent_runs=5,
        recursion_limit=500,
    )
    assert config.poll_interval_seconds == 30
    assert config.max_concurrent_runs == 5
    assert config.recursion_limit == 500


# --- test_subagents_acp_boolean_backstops ---

BACKSTOP_FIELDS = ("timeout_seconds", "max_turns")


GLOBAL_INT_FIELDS = ("timeout_seconds", "max_turns", "max_total_per_run")


@pytest.mark.parametrize("value", [True, False])
@pytest.mark.parametrize("field", BACKSTOP_FIELDS)
def test_override_backstops_reject_booleans(field: str, value: bool) -> None:
    with pytest.raises(ValidationError, match="must be an integer, not a boolean"):
        SubagentOverrideConfig(**{field: value})


@pytest.mark.parametrize("value", [True, False])
@pytest.mark.parametrize("field", BACKSTOP_FIELDS)
def test_custom_backstops_reject_booleans(field: str, value: bool) -> None:
    with pytest.raises(ValidationError, match="must be an integer, not a boolean"):
        CustomSubagentConfig(description="d", system_prompt="s", **{field: value})


@pytest.mark.parametrize("value", [True, False])
@pytest.mark.parametrize("field", GLOBAL_INT_FIELDS)
def test_global_backstops_reject_booleans(field: str, value: bool) -> None:
    with pytest.raises(ValidationError, match="must be an integer, not a boolean"):
        SubagentsAppConfig(**{field: value})


@pytest.mark.parametrize("field", BACKSTOP_FIELDS)
def test_override_backstops_keep_none_and_numeric_inputs(field: str) -> None:
    config = SubagentOverrideConfig(**{field: None})
    assert getattr(config, field) is None
    config = SubagentOverrideConfig(**{field: "30"})
    assert getattr(config, field) == 30


def test_custom_backstops_keep_numeric_inputs() -> None:
    config = CustomSubagentConfig(description="d", system_prompt="s", max_turns="25", timeout_seconds=600)
    assert config.max_turns == 25
    assert config.timeout_seconds == 600


def test_global_backstops_keep_numeric_inputs() -> None:
    config = SubagentsAppConfig(timeout_seconds="900", max_turns="40", max_total_per_run=8)
    assert config.timeout_seconds == 900
    assert config.max_turns == 40
    assert config.max_total_per_run == 8


@pytest.mark.parametrize("value", [True, False])
def test_acp_timeout_rejects_booleans(value: bool) -> None:
    with pytest.raises(ValidationError, match="must be an integer, not a boolean"):
        ACPAgentConfig(command="cmd", description="d", timeout_seconds=value)


def test_acp_timeout_keeps_numeric_input() -> None:
    config = ACPAgentConfig(command="cmd", description="d", timeout_seconds="600")
    assert config.timeout_seconds == 600


# --- test_numeric_config_guards ---


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
