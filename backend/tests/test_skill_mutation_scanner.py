from unittest.mock import AsyncMock

import pytest

from deerflow.config.app_config import AppConfig
from deerflow.skills.mutations.assets import PackageFile, PackageSnapshot
from deerflow.skills.security_scanner import ScanResult

CONTENT = b"---\nname: example\ndescription: Fine\n---\nHelpful instructions.\n"


def configuration(enabled=True):
    return AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}, "skill_scan": {"enabled": enabled}, "skill_evolution": {"security_fail_closed": False}})


@pytest.mark.asyncio
async def test_host_check_never_treats_disabled_scanner_as_allow(monkeypatch):
    from deerflow.skills.mutations.scanner import CandidateScanner

    model = AsyncMock(return_value=ScanResult("allow", "fine"))
    monkeypatch.setattr("deerflow.skills.mutations.scanner.scan_skill_content", model)
    result = await CandidateScanner(lambda: configuration(False)).scan(PackageSnapshot((PackageFile("SKILL.md", CONTENT, False),)), "example")
    assert result.decision == "unavailable"
    model.assert_not_called()


@pytest.mark.asyncio
async def test_host_scan_covers_support_files_and_forces_fail_closed(monkeypatch):
    from deerflow.skills.mutations.scanner import CandidateScanner

    model = AsyncMock(return_value=ScanResult("allow", "fine"))
    monkeypatch.setattr("deerflow.skills.mutations.scanner.scan_skill_content", model)
    scanner = CandidateScanner(configuration)
    package = PackageSnapshot((PackageFile("SKILL.md", CONTENT, False), PackageFile("references/help.md", b"Supporting advice", False)))
    result = await scanner.scan(package, "example")
    assert result.decision == "allow"
    assert result.policy_version == await scanner.policy_version()
    assert model.await_count == 2
    assert all(call.kwargs["app_config"].skill_evolution.security_fail_closed for call in model.await_args_list)


@pytest.mark.asyncio
async def test_static_block_prevents_model_scan(monkeypatch):
    from deerflow.skills.mutations.scanner import CandidateScanner

    model = AsyncMock(return_value=ScanResult("allow", "fine"))
    monkeypatch.setattr("deerflow.skills.mutations.scanner.scan_skill_content", model)
    package = PackageSnapshot((PackageFile("SKILL.md", CONTENT, False), PackageFile("scripts/run.py", b"eval(input())", True)))
    result = await CandidateScanner(configuration).scan(package, "example")
    assert result.decision == "reject"
    model.assert_not_called()


@pytest.mark.asyncio
async def test_scanner_resource_limit_is_not_partial_approval(monkeypatch):
    from deerflow.skills.mutations.scanner import CandidateScanner

    model = AsyncMock(return_value=ScanResult("allow", "fine"))
    monkeypatch.setattr("deerflow.skills.mutations.scanner.scan_skill_content", model)
    package = PackageSnapshot((PackageFile("SKILL.md", CONTENT, False), PackageFile("notes.txt", b"x" * (128 * 1024 + 1), False)))
    result = await CandidateScanner(configuration).scan(package, "example")
    assert result.decision == "unavailable"
    model.assert_not_called()
