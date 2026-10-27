"""The platform boundary shared by the skill-export test suites.

``deerflow.skills.export._capture`` feature-detects fd-based directory
walking and otherwise rejects every export with ``422
skill_export_unsupported`` (Windows is the main such platform). Every
suite that drives the real exporter must skip exactly where that guard
fires, and the mirror lives here so the per-file copies cannot drift.
"""

import os

import pytest

requires_safe_capture = pytest.mark.skipif(
    not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd or os.scandir not in os.supports_fd,
    reason="skill export capture needs os.O_NOFOLLOW and dir_fd directory walking, which this platform does not provide; export_manifest/build_skill_export return 422 skill_export_unsupported there",
)
