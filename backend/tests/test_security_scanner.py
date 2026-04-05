"""Tests for skill security scanning."""

import asyncio
from types import SimpleNamespace

from deerflow.skills.security_scanner import ScanDecision, _parse_scan_response, scan_content


def test_parse_allow_response():
    verdict = _parse_scan_response("DECISION: allow\nREASON: looks good", "skill")
    assert verdict.decision == ScanDecision.ALLOW
    assert verdict.reason == "looks good"


def test_parse_warn_response_for_skill():
    verdict = _parse_scan_response("DECISION: warn\nREASON: external link present", "skill")
    assert verdict.decision == ScanDecision.WARN
    assert "external link" in verdict.reason


def test_parse_warn_response_for_script_blocks():
    verdict = _parse_scan_response("DECISION: warn\nREASON: suspicious script", "script")
    assert verdict.decision == ScanDecision.BLOCK
    assert "suspicious script" in verdict.reason


def test_unparseable_skill_response_warns():
    verdict = _parse_scan_response("gibberish", "skill")
    assert verdict.decision == ScanDecision.WARN


def test_unparseable_script_response_blocks():
    verdict = _parse_scan_response("gibberish", "script")
    assert verdict.decision == ScanDecision.BLOCK


def test_scan_content_fail_open_for_skill(monkeypatch):
    class BrokenModel:
        async def ainvoke(self, _prompt):
            raise RuntimeError("scanner offline")

    monkeypatch.setattr("deerflow.config.memory_config.get_memory_config", lambda: SimpleNamespace(model_name="cheap"))
    monkeypatch.setattr("deerflow.models.create_chat_model", lambda **kwargs: BrokenModel())

    verdict = asyncio.run(scan_content("safe markdown", content_type="skill"))
    assert verdict.decision == ScanDecision.WARN
    assert "scanner offline" in verdict.reason


def test_scan_content_fail_closed_for_script(monkeypatch):
    class BrokenModel:
        async def ainvoke(self, _prompt):
            raise RuntimeError("scanner offline")

    monkeypatch.setattr("deerflow.config.memory_config.get_memory_config", lambda: SimpleNamespace(model_name="cheap"))
    monkeypatch.setattr("deerflow.models.create_chat_model", lambda **kwargs: BrokenModel())

    verdict = asyncio.run(scan_content("print('hi')", content_type="script"))
    assert verdict.decision == ScanDecision.BLOCK
    assert "scanner offline" in verdict.reason
