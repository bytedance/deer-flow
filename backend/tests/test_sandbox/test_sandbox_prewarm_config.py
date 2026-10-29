"""Operator controls bound speculative sandbox work without enabling it by default."""

import pytest
from pydantic import ValidationError

from deerflow.config.sandbox_config import SandboxConfig


def test_prewarm_defaults_are_opt_in_and_bounded():
    config = SandboxConfig(use="deerflow.community.aio_sandbox:AioSandboxProvider")
    assert config.prewarm is False
    assert config.prewarm_max_concurrent == 1


@pytest.mark.parametrize("value", [1, 4, "3"])
def test_prewarm_limit_accepts_positive_integers_and_environment_strings(value):
    config = SandboxConfig(use="example:Provider", prewarm_max_concurrent=value)
    assert config.prewarm_max_concurrent == int(value)


@pytest.mark.parametrize("value", [True, False, 0, -1, 1.5, "bad", None])
def test_prewarm_limit_rejects_invalid_values(value):
    with pytest.raises(ValidationError):
        SandboxConfig(use="example:Provider", prewarm_max_concurrent=value)
