"""Shared package-index environment setup for suites that invoke uv."""

from __future__ import annotations

import pytest


def apply_official_package_index(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin uv's default index and remove extra-index environment overrides.

    ``UV_DEFAULT_INDEX`` takes precedence over the legacy ``UV_INDEX_URL``;
    entries from ``UV_INDEX`` and ``UV_EXTRA_INDEX_URL`` take priority over
    the default index, so those environment channels are dropped.

    This only isolates environment-provided indexes. File-based indexes,
    including user ``uv.toml`` ``[[index]]`` entries and files selected by
    ``UV_CONFIG_FILE``, remain out of scope. Setting ``UV_NO_CONFIG`` would
    also suppress fixture-owned ``[tool.uv]`` settings needed by assertions.

    Suites opt in through their own autouse fixtures. Explicit environment
    overrides applied later by a test or subprocess helper retain precedence.
    """
    monkeypatch.setenv("UV_DEFAULT_INDEX", "https://pypi.org/simple")
    monkeypatch.delenv("UV_INDEX", raising=False)
    monkeypatch.delenv("UV_EXTRA_INDEX_URL", raising=False)
