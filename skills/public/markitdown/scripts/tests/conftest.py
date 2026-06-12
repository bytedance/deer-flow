"""Pytest fixtures for markitdown skill tests."""
import os
import pytest


@pytest.fixture
def mineru_env(monkeypatch):
    """Set MinerU env vars for the duration of one test."""
    monkeypatch.setenv("MINERU_API_URL", "http://mineru.lan:8000")
    monkeypatch.setenv("MINERU_API_KEY", "test-key-abc123")
    return {
        "url": "http://mineru.lan:8000",
        "key": "test-key-abc123",
    }


@pytest.fixture
def sample_text_file(tmp_path):
    """A small text file used to simulate a 'file to convert' in routing tests."""
    p = tmp_path / "doc.txt"
    p.write_text("hello world", encoding="utf-8")
    return p
