"""Tests for canonical MCP session scope construction and matching."""

import pytest

from deerflow.mcp_scope import (
    mcp_scope_belongs_to_thread,
    mcp_session_scope_key,
)


def test_legacy_scope_is_user_colon_thread():
    assert mcp_session_scope_key(user_id="u1", thread_id="t1", thread_incarnation=None) == "u1:t1"


def test_versioned_scope_is_prefixed_json_tuple():
    scope = mcp_session_scope_key(user_id="u1", thread_id="t1", thread_incarnation="inc-1")
    assert scope == 'v2:["u1","t1","inc-1"]'


def test_versioned_scope_disambiguates_ids_containing_the_legacy_delimiter():
    """The v2 encoding must stay unambiguous when an id contains ``:``."""
    left = mcp_session_scope_key(user_id="a:b", thread_id="c", thread_incarnation="inc")
    right = mcp_session_scope_key(user_id="a", thread_id="b:c", thread_incarnation="inc")
    assert left != right


def test_scope_rejects_invalid_incarnation():
    with pytest.raises(RuntimeError):
        mcp_session_scope_key(user_id="u1", thread_id="t1", thread_incarnation="")


@pytest.mark.parametrize(
    "scope_key",
    [
        "u1:t1",
        'v2:["u1","t1","inc-1"]',
        'v2:["u1","t1","inc-2"]',
    ],
)
def test_belongs_to_thread_matches_legacy_and_every_incarnation(scope_key):
    """Teardown matches the legacy scope and any versioned incarnation.

    A deleted thread cannot reliably know its current incarnation, and every
    generation of it is stale once the thread is gone (#5188).
    """
    assert mcp_scope_belongs_to_thread(scope_key, user_id="u1", thread_id="t1") is True


@pytest.mark.parametrize(
    "scope_key",
    [
        "u1:t2",
        "u2:t1",
        "u1:t10",
        "u10:t1",
        'v2:["u1","t2","inc-1"]',
        'v2:["u2","t1","inc-1"]',
    ],
)
def test_belongs_to_thread_rejects_other_user_or_thread(scope_key):
    assert mcp_scope_belongs_to_thread(scope_key, user_id="u1", thread_id="t1") is False


@pytest.mark.parametrize(
    "scope_key",
    [
        'v2:["u1","t1",null]',
        'v2:["u1","t1",1]',
        'v2:["u1","t1",""]',
    ],
)
def test_belongs_to_thread_matches_on_identity_not_incarnation_shape(scope_key):
    """A key carrying this thread's identity is claimed even when its third
    element is not a shape the current encoder emits.

    Matching is deliberately lenient about the incarnation: teardown must never
    *miss* a session belonging to the deleted thread, and an unexpected
    incarnation shape cannot make the session belong to somebody else.
    """
    assert mcp_scope_belongs_to_thread(scope_key, user_id="u1", thread_id="t1") is True


@pytest.mark.parametrize(
    "scope_key",
    [
        "",
        "v2:",
        "v2:not-json",
        'v2:{"user":"u1"}',
        'v2:["u1","t1"]',
        'v2:["u1","t1","inc","extra"]',
        'v3:["u1","t1","inc"]',
        "u1",
    ],
)
def test_belongs_to_thread_rejects_malformed_scopes(scope_key):
    """Unknown or structurally invalid encodings must not be claimed as this thread's."""
    assert mcp_scope_belongs_to_thread(scope_key, user_id="u1", thread_id="t1") is False
