"""Tests for build_principal_from_context — the single Principal builder.

This builder is the only sanctioned way to construct a Principal from runtime
context. Both Layer 1 (tool assembly) and Layer 2 (GuardrailAuthorizationAdapter)
must use it so identity semantics stay consistent.
"""

from __future__ import annotations

import pytest

from deerflow.authz.principal import build_principal_from_context


class TestPrincipalBuilderFields:
    """Verify all 7 Principal fields are explicitly constructed."""

    def test_empty_context(self):
        p = build_principal_from_context({}, default_role="user")
        assert p.user_id is None
        assert p.role == "user"
        assert p.oauth_provider is None
        assert p.oauth_id is None
        assert p.channel_user_id is None
        assert p.is_internal is False
        assert p.attributes == {}

    def test_full_field_mapping(self):
        context = {
            "user_id": "u1",
            "user_role": "admin",
            "oauth_provider": "github",
            "oauth_id": "gh-123",
            "channel_user_id": "ou_sender_1",
            "is_internal": True,
            "authz_attributes": {"department": "eng"},
        }
        p = build_principal_from_context(context, default_role="user")
        assert p.user_id == "u1"
        assert p.role == "admin"
        assert p.oauth_provider == "github"
        assert p.oauth_id == "gh-123"
        assert p.channel_user_id == "ou_sender_1"
        assert p.is_internal is True
        assert p.attributes == {"department": "eng"}

    def test_partial_context(self):
        context = {"user_id": "u1", "user_role": "user"}
        p = build_principal_from_context(context, default_role="admin")
        assert p.user_id == "u1"
        assert p.role == "user"
        assert p.oauth_provider is None
        assert p.oauth_id is None


class TestRoleResolution:
    """Role fallback rules."""

    def test_none_role_uses_default(self):
        p = build_principal_from_context({"user_role": None}, default_role="guest")
        assert p.role == "guest"

    def test_empty_string_role_uses_default(self):
        p = build_principal_from_context({"user_role": ""}, default_role="guest")
        assert p.role == "guest"

    def test_missing_role_uses_default(self):
        p = build_principal_from_context({}, default_role="guest")
        assert p.role == "guest"

    def test_unknown_role_preserved(self):
        """A non-empty but unknown role must NOT fall back to default_role."""
        p = build_principal_from_context({"user_role": "editor"}, default_role="user")
        assert p.role == "editor"


class TestIsInternalStrictBool:
    """is_internal must only be True when the value is strictly True."""

    @pytest.mark.parametrize(
        "value,expected",
        [
            (True, True),
            (False, False),
            (1, False),
            ("true", False),
            ("1", False),
            (None, False),
            ([], False),
            ({}, False),
        ],
    )
    def test_is_internal_strict_bool(self, value, expected):
        p = build_principal_from_context({"is_internal": value}, default_role="user")
        assert p.is_internal is expected


class TestAttributes:
    """Attributes copy and validation semantics."""

    def test_missing_attributes(self):
        p = build_principal_from_context({}, default_role="user")
        assert p.attributes == {}

    def test_none_attributes(self):
        p = build_principal_from_context({"authz_attributes": None}, default_role="user")
        assert p.attributes == {}

    def test_mapping_attributes_copied(self):
        attrs = {"team": "platform"}
        p = build_principal_from_context({"authz_attributes": attrs}, default_role="user")
        assert p.attributes == {"team": "platform"}
        # Mutating input after build must not affect Principal
        attrs["team"] = "changed"
        assert p.attributes["team"] == "platform"

    def test_empty_mapping_attributes(self):
        p = build_principal_from_context({"authz_attributes": {}}, default_role="user")
        assert p.attributes == {}

    @pytest.mark.parametrize(
        "invalid",
        [
            [("key", "value")],  # list of tuples (not a Mapping at runtime)
            "not a mapping",
            42,
            [1, 2, 3],
        ],
    )
    def test_non_mapping_attributes_raises_type_error(self, invalid):
        with pytest.raises(TypeError, match="authz_attributes must be a Mapping"):
            build_principal_from_context({"authz_attributes": invalid}, default_role="user")

    def test_type_error_includes_actual_type(self):
        with pytest.raises(TypeError, match="list"):
            build_principal_from_context({"authz_attributes": [1, 2]}, default_role="user")


class TestPureFunction:
    """Builder must not modify its input."""

    def test_input_not_modified(self):
        context = {"user_id": "u1", "user_role": "admin", "authz_attributes": {"k": "v"}}
        original = dict(context)
        build_principal_from_context(context, default_role="user")
        assert context == original
