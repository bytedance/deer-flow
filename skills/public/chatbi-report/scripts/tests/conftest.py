"""Pytest fixtures for chatbi-report skill scripts."""
import os
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))


@pytest.fixture
def sqlbot_env(monkeypatch):
    """Set SQLBOT_BASE_URL for the duration of one test (no API key per spec)."""
    monkeypatch.setenv("SQLBOT_BASE_URL", "http://sqlbot.lan:9070")
    return {"base_url": "http://sqlbot.lan:9070"}


@pytest.fixture
def fixture_dir() -> Path:
    """Path to backend/tests/chatbi_report/fixtures for integration-style unit tests."""
    return (
        Path(__file__).resolve().parents[5]
        / "backend"
        / "tests"
        / "chatbi_report"
        / "fixtures"
    )
