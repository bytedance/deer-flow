"""Tests for PAT token utilities and the personal access token repository."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from app.gateway.auth.pat import (
    PAT_ALLOWED_SCOPES,
    PAT_TOKEN_PREFIX,
    digest_matches,
    extract_bearer_token,
    generate_pat_token,
    pat_token_digest,
    validate_scopes,
)
from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.personal_access_tokens import PersonalAccessTokenRepository


@pytest_asyncio.fixture(autouse=True)
async def _close_persistence_engine():
    yield
    await close_engine()


async def _make_repo(tmp_path) -> PersonalAccessTokenRepository:
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    session_factory = get_session_factory()
    assert session_factory is not None
    return PersonalAccessTokenRepository(session_factory)


# ── Token utilities ───────────────────────────────────────────────────────


def test_generate_pat_token_format():
    token = generate_pat_token()
    assert token.startswith(PAT_TOKEN_PREFIX)
    body = token[len(PAT_TOKEN_PREFIX) :]
    assert len(body) == 43  # fixed width: 62^43 > 2^256 > 62^42
    assert body.isalnum()
    # Two draws must differ: CSPRNG, not a counter.
    assert token != generate_pat_token()


def test_base62_pads_to_fixed_width_for_leading_zero_and_all_zero_input():
    """``int.from_bytes`` discards leading zero bytes; the fixed-width pad
    keeps the token body exactly 43 chars for every draw, including the
    all-zero and single-leading-byte edges (review round 6, P3)."""
    from app.gateway.auth.pat import PAT_RANDOM_BYTES, _base62

    assert _base62(b"\x00" * PAT_RANDOM_BYTES) == "0" * 43
    assert _base62(b"\x00" * (PAT_RANDOM_BYTES - 1) + b"\x01") == "0" * 42 + "1"
    assert len(_base62(b"\xff" * PAT_RANDOM_BYTES)) == 43


def test_pat_token_digest_is_deterministic_and_constant_time_comparable():
    token = generate_pat_token()
    assert pat_token_digest(token) == pat_token_digest(token)
    assert len(pat_token_digest(token)) == 64
    assert digest_matches(pat_token_digest(token), token) is True
    # The mutated token must differ from the original even when the CSPRNG
    # tail already ends in "X" (1/62), or this assertion fails intermittently.
    mutated_tail = "X" if token[-1] != "X" else "Y"
    assert digest_matches(pat_token_digest(token), token[:-1] + mutated_tail) is False
    assert digest_matches(None, token) is False
    assert digest_matches("", token) is False


def test_extract_bearer_token_classifies_absent_scheme_and_credential():
    assert extract_bearer_token(None) is None
    assert extract_bearer_token("Bearer dfp_abc") == "dfp_abc"
    assert extract_bearer_token("bearer dfp_abc") == "dfp_abc"  # scheme is case-insensitive
    assert extract_bearer_token("Basic dXNlcg==") == ""  # present but unusable
    assert extract_bearer_token("Bearer ") == ""
    assert extract_bearer_token("Bearer") == ""


def test_validate_scopes_deduplicates_and_rejects_unknown():
    assert validate_scopes(["runs:read", "threads:read", "runs:read"]) == ["runs:read", "threads:read"]
    with pytest.raises(ValueError, match="Unknown PAT scopes"):
        validate_scopes(["runs:write"])  # not a route permission
    with pytest.raises(ValueError, match="at least one scope"):
        validate_scopes([])


def test_pat_scopes_stay_aligned_with_route_permissions():
    """PAT scopes are exactly the authz route permissions — fail on drift."""
    from app.gateway.authz import _ALL_PERMISSIONS

    assert PAT_ALLOWED_SCOPES == frozenset(_ALL_PERMISSIONS)


# ── Repository ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_and_resolve_by_digest_roundtrip(tmp_path):
    repo = await _make_repo(tmp_path)
    token = generate_pat_token()
    record = await repo.create(
        user_id="user-1",
        name="ci-runner",
        scopes=["runs:read"],
        token_digest=pat_token_digest(token),
    )
    assert record["user_id"] == "user-1"
    assert record["scopes"] == ["runs:read"]
    assert record["revoked_at"] is None

    resolved = await repo.get_active_by_digest(pat_token_digest(token))
    assert resolved is not None
    assert resolved["id"] == record["id"]
    assert resolved["token_digest"] == pat_token_digest(token)
    # Digest lookup never matches a different token.
    assert await repo.get_active_by_digest(pat_token_digest(generate_pat_token())) is None


@pytest.mark.asyncio
async def test_revoked_token_no_longer_resolves(tmp_path):
    repo = await _make_repo(tmp_path)
    token = generate_pat_token()
    record = await repo.create(user_id="user-1", name="temp", scopes=["runs:read"], token_digest=pat_token_digest(token))

    assert await repo.revoke(record["id"], "user-1") is True
    # Revoking twice is a no-op.
    assert await repo.revoke(record["id"], "user-1") is False
    assert await repo.get_active_by_digest(pat_token_digest(token)) is None


@pytest.mark.asyncio
async def test_revoke_is_scoped_to_the_owning_user(tmp_path):
    repo = await _make_repo(tmp_path)
    token = generate_pat_token()
    record = await repo.create(user_id="user-1", name="mine", scopes=["runs:read"], token_digest=pat_token_digest(token))

    assert await repo.revoke(record["id"], "user-2") is False  # not the owner
    assert await repo.get_active_by_digest(pat_token_digest(token)) is not None


@pytest.mark.asyncio
async def test_expired_token_no_longer_resolves(tmp_path):
    repo = await _make_repo(tmp_path)
    token = generate_pat_token()
    await repo.create(
        user_id="user-1",
        name="short-lived",
        scopes=["runs:read"],
        token_digest=pat_token_digest(token),
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    assert await repo.get_active_by_digest(pat_token_digest(token)) is None


@pytest.mark.asyncio
async def test_list_for_user_is_isolated_and_never_returns_raw_tokens(tmp_path):
    repo = await _make_repo(tmp_path)
    token = generate_pat_token()
    created = await repo.create(user_id="user-1", name="a", scopes=["runs:read"], token_digest=pat_token_digest(token))
    await repo.create(user_id="user-2", name="b", scopes=["threads:read"], token_digest=pat_token_digest(generate_pat_token()))

    listed = await repo.list_for_user("user-1")
    assert [item["id"] for item in listed] == [created["id"]]
    assert listed[0]["token_digest"] == pat_token_digest(token)  # digest only; raw token never persisted


@pytest.mark.asyncio
async def test_token_digest_unique_constraint(tmp_path):
    repo = await _make_repo(tmp_path)
    digest = pat_token_digest(generate_pat_token())
    await repo.create(user_id="user-1", name="a", scopes=["runs:read"], token_digest=digest)
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        await repo.create(user_id="user-1", name="dup", scopes=["runs:read"], token_digest=digest)


@pytest.mark.asyncio
async def test_touch_last_used_is_throttled(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    session_factory = get_session_factory()
    repo = PersonalAccessTokenRepository(session_factory, last_used_write_interval_seconds=300.0)
    record = await repo.create(user_id="user-1", name="t", scopes=["runs:read"], token_digest=pat_token_digest(generate_pat_token()))

    await repo.touch_last_used(record["id"])
    first = (await repo.list_for_user("user-1"))[0]["last_used_at"]
    assert first is not None

    # A second touch inside the throttle window must not produce a write.
    await repo.touch_last_used(record["id"])
    second = (await repo.list_for_user("user-1"))[0]["last_used_at"]
    assert second == first

    # After the window elapses the next touch writes again.
    repo._last_used_written_at.clear()
    await repo.touch_last_used(record["id"])
    third = (await repo.list_for_user("user-1"))[0]["last_used_at"]
    assert third != first


@pytest.mark.asyncio
async def test_touch_last_used_never_raises_on_unknown_id(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    repo = PersonalAccessTokenRepository(get_session_factory())
    await repo.touch_last_used("no-such-pat")  # update affects 0 rows; still a commit
