"""YAML booleans must not coerce into the local-login throttle policy.

``auth.local`` sits next to the genuine booleans ``allow_registration`` and the
OIDC provisioning flags, so ``lockout_seconds: true`` loads cleanly and Pydantic
coerces it to ``1.0``. ``_login_throttle_policy()`` feeds that value straight to
``now < locked_at + lockout_seconds`` in ``app/gateway/routers/auth.py``, which
turns the default five-minute IP lockout into a one-second one — the brute-force
backstop stays "configured" while doing nothing. ``max_login_attempts`` is the
same typo two lines away; ``ge=2`` happens to reject ``1`` today, but the
reporter blames the threshold rather than the boolean. Both fields now use the
shared ``reject_boolean`` guard, matching the app-config, scheduler and
tool-output guards already in the repo.
"""

import pytest
from pydantic import ValidationError

from deerflow.config.auth_config import LocalAuthConfig

THROTTLE_FIELDS = (("max_login_attempts", "an integer"), ("lockout_seconds", "a number"))


@pytest.mark.parametrize("value", [True, False])
@pytest.mark.parametrize(("field", "kind"), THROTTLE_FIELDS)
def test_throttle_policy_rejects_booleans(field: str, kind: str, value: bool) -> None:
    with pytest.raises(ValidationError, match=f"must be {kind}, not a boolean"):
        LocalAuthConfig(**{field: value})


@pytest.mark.parametrize("field", [field for field, _ in THROTTLE_FIELDS])
def test_throttle_policy_keeps_numeric_inputs(field: str) -> None:
    config = LocalAuthConfig(**{field: 60})
    assert getattr(config, field) == 60
    config = LocalAuthConfig(**{field: "90"})
    assert getattr(config, field) == 90


def test_throttle_policy_defaults_are_unchanged() -> None:
    config = LocalAuthConfig()
    assert config.max_login_attempts == 5
    assert config.lockout_seconds == 300.0
