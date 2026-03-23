"""Tests for LangGraph thread metadata utilities."""

import pytest

from deerflow.agents.thread_metadata import (
    filter_threads_by_user,
    get_thread_metadata,
    get_user_id_from_metadata,
)
from deerflow.config.multi_tenant_config import load_multi_tenant_config_from_dict, reset_multi_tenant_config


@pytest.fixture(autouse=True)
def reset_config():
    """Reset multi-tenant config before each test."""
    reset_multi_tenant_config()
    yield
    reset_multi_tenant_config()


def test_get_thread_metadata_with_user_id():
    """Test get_thread_metadata with explicit user_id."""
    load_multi_tenant_config_from_dict({"enabled": False, "default_user_id": "default"})
    metadata = get_thread_metadata(user_id="user-123")
    assert metadata == {"user_id": "user-123"}


def test_get_thread_metadata_without_user_id_single_tenant():
    """Test get_thread_metadata without user_id in single-tenant mode."""
    load_multi_tenant_config_from_dict({"enabled": False, "default_user_id": "default"})
    metadata = get_thread_metadata()
    assert metadata == {"user_id": "default"}


def test_get_thread_metadata_multi_tenant():
    """Test get_thread_metadata in multi-tenant mode."""
    load_multi_tenant_config_from_dict({"enabled": True, "default_user_id": "default"})
    metadata = get_thread_metadata(user_id="user-456")
    assert metadata == {"user_id": "user-456"}


def test_get_user_id_from_metadata():
    """Test extracting user_id from metadata."""
    metadata = {"user_id": "user-789"}
    user_id = get_user_id_from_metadata(metadata)
    assert user_id == "user-789"


def test_get_user_id_from_metadata_empty():
    """Test extracting user_id from empty metadata."""
    load_multi_tenant_config_from_dict({"enabled": False, "default_user_id": "default"})
    user_id = get_user_id_from_metadata({})
    assert user_id == "default"


def test_filter_threads_by_user():
    """Test filtering threads by user."""
    load_multi_tenant_config_from_dict({"enabled": True, "default_user_id": "default"})
    threads = [
        {"thread_id": "thread-1", "metadata": {"user_id": "user-1"}},
        {"thread_id": "thread-2", "metadata": {"user_id": "user-2"}},
        {"thread_id": "thread-3", "metadata": {"user_id": "user-1"}},
        {"thread_id": "thread-4", "metadata": {}},
    ]

    filtered = filter_threads_by_user(threads, user_id="user-1")
    assert len(filtered) == 2
    assert filtered[0]["thread_id"] == "thread-1"
    assert filtered[1]["thread_id"] == "thread-3"


def test_filter_threads_single_tenant():
    """Test that single-tenant mode returns all threads."""
    load_multi_tenant_config_from_dict({"enabled": False})
    threads = [
        {"thread_id": "thread-1", "metadata": {"user_id": "user-1"}},
        {"thread_id": "thread-2", "metadata": {"user_id": "user-2"}},
    ]

    filtered = filter_threads_by_user(threads, user_id="user-1")
    assert len(filtered) == 2  # All threads returned in single-tenant mode


def test_filter_threads_multi_tenant():
    """Test that multi-tenant mode filters by user."""
    load_multi_tenant_config_from_dict({"enabled": True})
    threads = [
        {"thread_id": "thread-1", "metadata": {"user_id": "user-1"}},
        {"thread_id": "thread-2", "metadata": {"user_id": "user-2"}},
    ]

    filtered = filter_threads_by_user(threads, user_id="user-1")
    assert len(filtered) == 1
    assert filtered[0]["thread_id"] == "thread-1"
