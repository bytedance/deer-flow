"""Unit tests for the M1 ``User`` model widening (plan M1-5, RFC §11.5).

Two backward-compatibility guarantees we must lock down:

1. ``system_role`` was a ``Literal["admin", "user"]`` and is now ``str`` —
   it must continue to round-trip ``"admin"`` / ``"user"`` AND accept
   new arbitrary strings (e.g. ``"project_manager"``) without raising.
2. ``roles: list[str]`` defaults to ``[]`` so a JWT or DB row that does
   not include the field still deserialises cleanly.
"""

from __future__ import annotations

import json
from uuid import UUID

from app.gateway.auth.models import User, UserResponse


def _make_user(**overrides) -> User:
    return User(email="alice@example.com", **overrides)


def test_user_roles_defaults_to_empty_list() -> None:
    """Backwards-compat: omitting ``roles`` keeps the previous shape."""
    user = _make_user()
    assert user.roles == []


def test_user_system_role_defaults_to_user() -> None:
    """Default ``system_role`` is still ``"user"`` — no regression."""
    user = _make_user()
    assert user.system_role == "user"


def test_user_system_role_accepts_arbitrary_string() -> None:
    """Type widened from Literal to str — new enterprise roles parse."""
    user = _make_user(system_role="project_manager")
    assert user.system_role == "project_manager"


def test_user_system_role_round_trips_legacy_values() -> None:
    """Existing JWTs encoding ``"admin"`` / ``"user"`` deserialise unchanged."""
    payload = {
        "email": "bob@example.com",
        "system_role": "admin",
        "id": str(UUID("00000000-0000-0000-0000-000000000001")),
    }
    user = User.model_validate(payload)
    assert user.system_role == "admin"


def test_user_roles_round_trip_via_json() -> None:
    """``roles`` must survive a JSON round-trip without rewrapping."""
    user = _make_user(roles=["admin", "viewer"])
    dumped = user.model_dump(mode="json")
    assert dumped["roles"] == ["admin", "viewer"]

    rehydrated = User.model_validate(json.loads(json.dumps(dumped)))
    assert rehydrated.roles == ["admin", "viewer"]


def test_user_roles_accepts_unknown_strings() -> None:
    """``roles`` is ``list[str]`` not ``list[Role]`` — provider validates later.

    Storing the raw string at the model level keeps the data layer stable
    while ``RbacPermissionProvider._resolve_roles`` handles unknown values
    (warn-and-drop). See ``test_rbac_permission_provider.py``.
    """
    user = _make_user(roles=["admin", "ghost", "future_role"])
    assert user.roles == ["admin", "ghost", "future_role"]


def test_user_roles_is_a_list_not_a_set() -> None:
    """Order matters for some downstream consumers (e.g. multi-role display)."""
    user = _make_user(roles=["viewer", "admin"])
    # exact order preserved
    assert user.roles[0] == "viewer"
    assert user.roles[1] == "admin"


def test_user_omitting_roles_is_equivalent_to_empty() -> None:
    """A pre-M1 JWT without ``roles`` must parse identically to ``roles=[]``."""
    without = User.model_validate({"email": "no-roles@example.com"})
    with_empty = User.model_validate({"email": "with-empty@example.com", "roles": []})
    assert without.roles == with_empty.roles == []


def test_user_response_carries_roles() -> None:
    """``UserResponse`` (the wire DTO) must echo ``roles`` on its way out."""
    resp = UserResponse(
        id="00000000-0000-0000-0000-000000000001",
        email="x@example.com",
        system_role="admin",
        roles=["admin"],
    )
    dumped = resp.model_dump()
    assert dumped["roles"] == ["admin"]
    assert dumped["system_role"] == "admin"


def test_user_response_defaults_roles_to_empty() -> None:
    """Pre-M1 callers that omit ``roles`` on UserResponse must still validate."""
    resp = UserResponse(
        id="00000000-0000-0000-0000-000000000001",
        email="x@example.com",
        system_role="user",
    )
    assert resp.roles == []
