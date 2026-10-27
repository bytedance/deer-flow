"""Compatibility exports for the native SkillScan implementation."""

from deerflow.skills.skillscan import (
    SecurityFinding as StaticFinding,
)
from deerflow.skills.skillscan import (
    StaticScanBlockedError,
    StaticScannerError,
    enforce_static_scan,
    format_static_findings,
    scan_archive_preflight,
    scan_skill_dir,
    skill_scan_enabled,
)

__all__ = [
    "StaticFinding",
    "StaticScanBlockedError",
    "StaticScannerError",
    "enforce_static_scan",
    "format_static_findings",
    "scan_archive_preflight",
    "scan_skill_dir",
    "skill_scan_enabled",
]
