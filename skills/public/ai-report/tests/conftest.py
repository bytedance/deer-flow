"""Shared pytest fixtures for ai-report tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 把 scripts/ 加入 sys.path, 让 `import parse_md` 等不报 ModuleNotFoundError
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
EXAMPLE_DIR = Path(__file__).resolve().parent.parent / "example"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def example_dir() -> Path:
    return EXAMPLE_DIR


@pytest.fixture
def scripts_dir() -> Path:
    return SCRIPTS_DIR