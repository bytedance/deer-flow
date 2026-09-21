"""Fail-closed checks of exact detached packages, never model-visible activation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

from deerflow.skills.mutations.assets import PackageSnapshot
from deerflow.skills.mutations.validation import MAX_MAIN_BYTES, PARSER_VERSION
from deerflow.skills.package_files import is_code_file
from deerflow.skills.security_scanner import scan_skill_content
from deerflow.skills.skillscan.orchestrator import scan_skill_dir
from deerflow.utils.file_io import await_drained

CHECK_POLICY_VERSION = "skill-mutation-check-v1"
MAX_MODEL_FILES = 32
MAX_MODEL_BYTES = 1024 * 1024
CHECK_TIMEOUT_SECONDS = 120


@dataclass(frozen=True)
class ScanVerdict:
    decision: str
    reason_code: str
    policy_version: str


class CandidateScanner:
    def __init__(self, config_provider):
        self._config_provider = config_provider

    @staticmethod
    def _policy(config):
        # Credentials never enter the returned value. Model configuration and
        # explicit code-policy versions invalidate approvals after changes.
        models = [model.model_dump(mode="json", exclude={"api_key"}) for model in config.models]
        policy = [CHECK_POLICY_VERSION, PARSER_VERSION, config.skill_scan.enabled, config.skill_evolution.moderation_model_name, models]
        return hashlib.sha256(json.dumps(policy, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    async def policy_version(self):
        return await asyncio.to_thread(self.policy_version_sync)

    def policy_version_sync(self):
        """Revalidate policy during short guarded publication admission."""
        return self._policy(self._config_provider())

    @staticmethod
    def _prepare(package: PackageSnapshot):
        text_files = []
        total = 0
        for item in package.files:
            executable = item.executable or is_code_file(item.path, item.content[:4096])
            try:
                content = item.content.decode("utf-8")
            except UnicodeError:
                if executable or item.path == "SKILL.md":
                    return None, None
                continue  # Binary assets still receive the whole-package static scan.
            if "\0" in content:
                if executable or item.path == "SKILL.md":
                    return None, None
                continue
            total += len(item.content)
            if len(item.content) > MAX_MAIN_BYTES or total > MAX_MODEL_BYTES or len(text_files) >= MAX_MODEL_FILES:
                return None, None
            text_files.append((item.path, content, executable))
        with tempfile.TemporaryDirectory(prefix="deerflow-host-check-") as temporary:
            root = Path(temporary)
            for item in package.files:
                target = root / item.path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(item.content)
                target.chmod(0o700 if item.executable else 0o600)
            result = scan_skill_dir(root)
        return result, text_files

    async def scan(self, package: PackageSnapshot, name: str) -> ScanVerdict:
        policy = "unavailable"
        try:
            config = await asyncio.to_thread(self._config_provider)
            policy = self._policy(config)
            if not config.skill_scan.enabled:
                return ScanVerdict("unavailable", "SCANNER_DISABLED", policy)
            # This capability never inherits the old manual path's fail-open flag.
            config = config.model_copy(deep=True)
            config.skill_evolution.security_fail_closed = True
            async with asyncio.timeout(CHECK_TIMEOUT_SECONDS):
                result, files = await await_drained(asyncio.to_thread(self._prepare, package))
                if result is None:
                    return ScanVerdict("unavailable", "SCAN_LIMIT_EXCEEDED", policy)
                if result["scanner_errors"]:
                    return ScanVerdict("unavailable", "SCANNER_INCOMPLETE", policy)
                if result["blocked"]:
                    return ScanVerdict("reject", "STATIC_SCAN_REJECTED", policy)
                for path, content, executable in files:
                    findings = [finding for finding in result["findings"] if finding["file"] == path]
                    scanned = await scan_skill_content(content, executable=executable, location=f"{name}/{path}", app_config=config, static_findings=findings, redact_diagnostics=True)
                    if not scanned.available:
                        return ScanVerdict("unavailable", "SCANNER_UNAVAILABLE", policy)
                    if scanned.decision == "block" or (executable and scanned.decision != "allow"):
                        return ScanVerdict("reject", "MODEL_SCAN_REJECTED", policy)
            return ScanVerdict("allow", "CHECK_PASSED", policy)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Error details can include model/provider content. Return codes only.
            return ScanVerdict("unavailable", "SCANNER_UNAVAILABLE", policy)
