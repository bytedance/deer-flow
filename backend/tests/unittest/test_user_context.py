"""Tests for the runtime actor-context bridge."""

from types import SimpleNamespace

import pytest

from deerflow.runtime.actor_context import (
    ActorContext,
    DEFAULT_USER_ID,
    get_actor_context,
    get_effective_user_id,
    require_actor_context,
    reset_actor_context,
    bind_actor_context,
)


@pytest.mark.no_auto_user
def test_default_is_none():
    """Before any set, contextvar returns None."""
    assert get_actor_context() is None


@pytest.mark.no_auto_user
def test_set_and_reset_roundtrip():
    """Binding returns a token that reset restores."""
    actor = ActorContext(user_id="user-1")
    token = bind_actor_context(actor)
    try:
        assert get_actor_context() == actor
    finally:
        reset_actor_context(token)
    assert get_actor_context() is None


@pytest.mark.no_auto_user
def test_require_current_user_raises_when_unset():
    """require_actor_context raises RuntimeError if no actor is bound."""
    assert get_actor_context() is None
    with pytest.raises(RuntimeError, match="without actor context"):
        require_actor_context()


@pytest.mark.no_auto_user
def test_require_current_user_returns_user_when_set():
    """require_actor_context returns the bound actor."""
    actor = ActorContext(user_id="user-2")
    token = bind_actor_context(actor)
    try:
        assert require_actor_context() == actor
    finally:
        reset_actor_context(token)


@pytest.mark.no_auto_user
def test_protocol_accepts_duck_typed():
    actor = ActorContext(user_id="user-3")
    assert actor.user_id == "user-3"


# ---------------------------------------------------------------------------
# get_effective_user_id / DEFAULT_USER_ID tests
# ---------------------------------------------------------------------------


def test_default_user_id_is_default():
    assert DEFAULT_USER_ID == "default"


@pytest.mark.no_auto_user
def test_effective_user_id_returns_default_when_no_user():
    """No user in context -> fallback to DEFAULT_USER_ID."""
    assert get_effective_user_id() == "default"


@pytest.mark.no_auto_user
def test_effective_user_id_returns_user_id_when_set():
    actor = ActorContext(user_id="u-abc-123")
    token = bind_actor_context(actor)
    try:
        assert get_effective_user_id() == "u-abc-123"
    finally:
        reset_actor_context(token)


@pytest.mark.no_auto_user
def test_effective_user_id_coerces_to_str():
    """User.id might be a UUID object; must come back as str."""
    import uuid
    uid = uuid.uuid4()

    actor = ActorContext(user_id=str(uid))
    token = bind_actor_context(actor)
    try:
        assert get_effective_user_id() == str(uid)
    finally:
        reset_actor_context(token)
