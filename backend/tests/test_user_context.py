"""Tests for runtime.user_context — contextvar three-state semantics.

These tests opt out of the autouse contextvar fixture (added in
commit 6) because they explicitly test the cases where the contextvar
is set or unset.
"""

from types import SimpleNamespace

import pytest

from deerflow.runtime.user_context import (
    CurrentUser,
    get_current_user,
    require_current_user,
    reset_current_user,
    set_current_user,
)


@pytest.mark.no_auto_user
def test_default_is_none():
    """Before any set, contextvar returns None."""
    assert get_current_user() is None


@pytest.mark.no_auto_user
def test_set_and_reset_roundtrip():
    """set_current_user returns a token that reset restores."""
    user = SimpleNamespace(id="user-1")
    token = set_current_user(user)
    try:
        assert get_current_user() is user
    finally:
        reset_current_user(token)
    assert get_current_user() is None


@pytest.mark.no_auto_user
def test_require_current_user_raises_when_unset():
    """require_current_user raises RuntimeError if contextvar is unset."""
    assert get_current_user() is None
    with pytest.raises(RuntimeError, match="without user context"):
        require_current_user()


@pytest.mark.no_auto_user
def test_require_current_user_returns_user_when_set():
    """require_current_user returns the user when contextvar is set."""
    user = SimpleNamespace(id="user-2")
    token = set_current_user(user)
    try:
        assert require_current_user() is user
    finally:
        reset_current_user(token)


@pytest.mark.no_auto_user
def test_protocol_accepts_duck_typed():
    """CurrentUser is a runtime_checkable Protocol matching any .id-bearing object."""
    user = SimpleNamespace(id="user-3")
    assert isinstance(user, CurrentUser)


@pytest.mark.no_auto_user
def test_protocol_rejects_no_id():
    """Objects without .id do not satisfy CurrentUser Protocol."""
    not_a_user = SimpleNamespace(email="no-id@example.com")
    assert not isinstance(not_a_user, CurrentUser)
