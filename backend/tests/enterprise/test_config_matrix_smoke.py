"""Startup smoke tests for :class:`EnterpriseConfig`.

These complement the dedicated validator unit tests by re-asserting that
the validator fires inside the *normal* ``EnterpriseConfig(...)``
constructor path — i.e. the path AppConfig hits during gateway startup.
No FastAPI lifespan is spun up; constructing the config is enough to
trigger the ``@model_validator(mode="after")`` defined on
:class:`EnterpriseConfig`.

Matrix layout (mirrors spec §4.1):

+-------------------------------------------------------------------+------------+
| Combination                                                       | Expected   |
+===================================================================+============+
| enterprise.enabled=false, all submodules false                    | ok         |
| enterprise.enabled=true, rbac only                                | ok         |
| enterprise.enabled=true, audit only                               | ok         |
| enterprise.enabled=true, all submodules true                      | ok         |
| enterprise.enabled=true, approval=true, rbac=false                | error      |
| enterprise.enabled=true, approval=true, audit=false               | error      |
| enterprise.enabled=true, oidc=true, rbac=false                    | ok + warn  |
| enterprise.enabled=false, audit=true                              | ok + warn  |
+-------------------------------------------------------------------+------------+

Tasks 8 (illegal combinations) and 9 (warning combinations) append to
this file. The ``logging`` and ``ValidationError`` imports below are
intentionally kept now even though Task 7's legal cases do not consume
them — Tasks 8/9 will.
"""

from __future__ import annotations

import logging  # noqa: F401  -- used by Task 9 warning combinations

import pytest
from pydantic import ValidationError

from deerflow.enterprise.config import (
    ApprovalConfig,
    AuditConfig,
    EnterpriseAuthConfig,
    EnterpriseConfig,
    OIDCConfig,
    RbacConfig,
)


def _cfg(**kw) -> dict:
    """Helper to build kwargs with sane defaults so tests stay terse."""
    return kw


# ---------------------------------------------------------------------------
# Task 7 — legal combinations
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        # 1. enterprise disabled, everything else default-off
        _cfg(enabled=False),
        # 2. enterprise enabled, RBAC only
        _cfg(enabled=True, rbac=RbacConfig(enabled=True)),
        # 3. enterprise enabled, audit only (sign_key set so no signing warning fires)
        _cfg(enabled=True, audit=AuditConfig(enabled=True, sign_key="x")),
        # 4. enterprise enabled, every sub-module enabled
        #    OIDC lives under ``auth`` on EnterpriseConfig (see
        #    EnterpriseAuthConfig), not as a top-level field, so we wrap
        #    it accordingly. EnterpriseConfig uses extra="forbid", which
        #    would reject a bare ``oidc=...`` kwarg.
        _cfg(
            enabled=True,
            rbac=RbacConfig(enabled=True),
            audit=AuditConfig(enabled=True, sign_key="x"),
            approval=ApprovalConfig(enabled=True),
            auth=EnterpriseAuthConfig(
                oidc=OIDCConfig(
                    enabled=True,
                    issuer="https://idp.example",
                    client_id="c",
                    client_secret="s",
                ),
            ),
        ),
    ],
)
def test_legal_combinations_parse_clean(kwargs) -> None:
    """Each legal combination must construct without raising."""
    cfg = EnterpriseConfig(**kwargs)
    assert cfg is not None


# ---------------------------------------------------------------------------
# Task 8 — illegal combinations (fail-fast)
# ---------------------------------------------------------------------------


def test_approval_without_rbac_raises() -> None:
    """approver lookup needs RBAC; without it no ticket can be answered."""
    with pytest.raises(ValidationError) as exc:
        EnterpriseConfig(
            enabled=True,
            audit=AuditConfig(enabled=True, sign_key="x"),
            approval=ApprovalConfig(enabled=True),
            rbac=RbacConfig(enabled=False),
        )
    assert "rbac" in str(exc.value).lower()


def test_approval_without_audit_raises() -> None:
    """Approval decisions must be auditable; degrading audit defeats the workflow."""
    with pytest.raises(ValidationError) as exc:
        EnterpriseConfig(
            enabled=True,
            rbac=RbacConfig(enabled=True),
            audit=AuditConfig(enabled=False),
            approval=ApprovalConfig(enabled=True),
        )
    assert "audit" in str(exc.value).lower()
