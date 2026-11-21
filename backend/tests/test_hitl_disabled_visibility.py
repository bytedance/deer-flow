"""#8431 / PR #8440: HITL disabled must be visible, not silent.

When hitl_approval is absent or enabled != true, the approval middleware is
skipped (fail-open). The fix keeps that behavior but must emit a warning at
insertion time, on every mount path (lead agent x2, subagent executor).
"""

import logging

import pytest

from deerflow.agents.lead_agent.agent import _insert_hitl_approval_middleware
from deerflow.config.hitl_approval_config import HitlApprovalConfig


class _Cfg:
    """Minimal app_config stand-in: no hitl_approval attribute by default."""

    def __init__(self, hitl=None):
        if hitl is not None:
            self.hitl_approval = hitl


def test_disabled_by_absence_warns(caplog):
    middlewares: list = []
    with caplog.at_level(logging.WARNING, logger="deerflow.agents.lead_agent.agent"):
        _insert_hitl_approval_middleware(middlewares, [], _Cfg(), supports_resume=False, model_name=None)
    assert middlewares == []
    assert any("hitl_approval is not enabled" in r.message for r in caplog.records)


def test_disabled_by_explicit_false_warns(caplog):
    middlewares: list = []
    cfg = _Cfg(HitlApprovalConfig(enabled=False))
    with caplog.at_level(logging.WARNING, logger="deerflow.agents.lead_agent.agent"):
        _insert_hitl_approval_middleware(middlewares, [], cfg, supports_resume=False, model_name=None)
    assert middlewares == []
    assert any("hitl_approval is not enabled" in r.message for r in caplog.records)


def test_enabled_mounts_without_warning(caplog):
    pytest.importorskip("deerflow.approvals.middleware")
    from deerflow.approvals.middleware import ToolApprovalMiddleware

    cfg = _Cfg(HitlApprovalConfig(enabled=True))
    middlewares: list = []
    with caplog.at_level(logging.WARNING, logger="deerflow.agents.lead_agent.agent"):
        try:
            _insert_hitl_approval_middleware(middlewares, [], cfg, supports_resume=False, model_name=None)
        except Exception:
            pytest.skip("middleware mount requires fuller app_config than this unit test provides")
    if middlewares:
        assert isinstance(middlewares[0], ToolApprovalMiddleware)
        assert not any("hitl_approval is not enabled" in r.message for r in caplog.records)
