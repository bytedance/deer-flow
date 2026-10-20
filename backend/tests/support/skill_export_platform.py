"""The platform boundary shared by the skill-export and skill-mutation test suites.

``deerflow.skills.export._capture`` feature-detects fd-based directory
walking and otherwise rejects every export with ``422
skill_export_unsupported`` (Windows is the main such platform). Every
suite that drives the real exporter must skip exactly where that guard
fires, and the mirror lives here so the per-file copies cannot drift.

The skill-mutation host has the same shape one tier up:
``HostSkillMutationService._authorize`` and ``PublicationTopology.acquire``
raise ``UNSUPPORTED_TOPOLOGY`` on ``os.name != "posix"``, and
``capture_package`` rejects it with ``UNSUPPORTED_ASSET``. Suites that drive
them skip through :data:`requires_posix_host` for the same reason.
"""

import os

import pytest

requires_safe_capture = pytest.mark.skipif(
    not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd or os.scandir not in os.supports_fd,
    reason="skill export capture needs os.O_NOFOLLOW and dir_fd directory walking, which this platform does not provide; export_manifest/build_skill_export return 422 skill_export_unsupported there",
)

requires_posix_host = pytest.mark.skipif(
    os.name != "posix",
    reason=(
        "the host skill-mutation service is POSIX-only: "
        "HostSkillMutationService._authorize and PublicationTopology.acquire raise "
        'UNSUPPORTED_TOPOLOGY on os.name != "posix", and capture_package rejects it '
        "with UNSUPPORTED_ASSET (it needs os.O_NOFOLLOW and dir_fd directory walking)"
    ),
)
