"""Tests for the built-in RbacAuthorizationProvider."""

from __future__ import annotations

import asyncio

import pytest

from deerflow.authz.provider import AuthzRequest, Principal
from deerflow.authz.rbac import RbacAuthorizationProvider

# --- Helpers ---


def _make_request(
    *,
    role: str = "user",
    resource: str = "tool",
    action: str = "call",
    target: str = "bash",
) -> AuthzRequest:
    return AuthzRequest(
        principal=Principal(role=role),
        resource=resource,
        action=action,
        target=target,
    )


def _provider(roles: dict) -> RbacAuthorizationProvider:
    return RbacAuthorizationProvider(roles=roles)


# --- Allow semantics ---


class TestAllowSemantics:
    """Verify all forms of `allow` configuration."""

    def test_wildcard_allow(self):
        p = _provider({"user": {"tools": {"allow": "*"}}})
        assert p.authorize(_make_request(target="bash")).allow is True
        assert p.authorize(_make_request(target="write_file")).allow is True

    def test_boolean_true_allow(self):
        p = _provider({"user": {"tools": {"allow": True}}})
        assert p.authorize(_make_request(target="bash")).allow is True

    def test_boolean_false_deny_all(self):
        p = _provider({"user": {"tools": {"allow": False}}})
        assert p.authorize(_make_request(target="bash")).allow is False
        assert p.authorize(_make_request(target="web_search")).allow is False

    def test_list_allow(self):
        p = _provider({"user": {"tools": {"allow": ["web_search", "read_file"]}}})
        assert p.authorize(_make_request(target="web_search")).allow is True
        assert p.authorize(_make_request(target="read_file")).allow is True
        assert p.authorize(_make_request(target="bash")).allow is False

    def test_empty_list_deny_all(self):
        p = _provider({"user": {"tools": {"allow": []}}})
        assert p.authorize(_make_request(target="bash")).allow is False

    def test_allow_missing_defaults_to_allow_all(self):
        """Missing `allow` means unrestricted (deny still applies)."""
        p = _provider({"user": {"tools": {"deny": ["bash"]}}})
        assert p.authorize(_make_request(target="bash")).allow is False
        assert p.authorize(_make_request(target="web_search")).allow is True


# --- Deny semantics ---


class TestDenySemantics:
    """Deny always wins over allow."""

    def test_deny_overrides_wildcard(self):
        p = _provider({"user": {"tools": {"allow": "*", "deny": ["bash"]}}})
        assert p.authorize(_make_request(target="bash")).allow is False
        assert p.authorize(_make_request(target="web_search")).allow is True

    def test_deny_overrides_list_allow(self):
        p = _provider({"user": {"tools": {"allow": ["bash", "web_search"], "deny": ["bash"]}}})
        assert p.authorize(_make_request(target="bash")).allow is False
        assert p.authorize(_make_request(target="web_search")).allow is True

    def test_deny_overrides_boolean_true(self):
        p = _provider({"user": {"tools": {"allow": True, "deny": ["bash"]}}})
        assert p.authorize(_make_request(target="bash")).allow is False


# --- Resource mapping ---


class TestResourceMapping:
    """tool → tools, model → models, etc."""

    @pytest.mark.parametrize(
        ("request_alias", "config_key"),
        [
            ("tool", "tools"),
            ("model", "models"),
            ("skill", "skills"),
            ("mcp_server", "mcp_servers"),
            ("route", "routes"),
        ],
    )
    def test_reserved_request_alias_is_rejected(self, request_alias, config_key):
        with pytest.raises(ValueError, match=rf"resource key '{request_alias}'.*use '{config_key}'"):
            _provider({"user": {request_alias: {"allow": []}}})

    def test_alias_is_rejected_when_mapped_key_is_also_configured(self):
        with pytest.raises(ValueError, match=r"resource key 'tool'.*use 'tools'"):
            _provider(
                {
                    "user": {
                        "tools": {"allow": "*"},
                        "tool": {"allow": []},
                    }
                }
            )

    def test_same_name_mapping_is_valid(self):
        p = _provider({"user": {"sandbox": {"allow": []}}})
        assert p.authorize(_make_request(resource="sandbox", target="default")).allow is False

    def test_tool_maps_to_tools(self):
        p = _provider({"user": {"tools": {"allow": ["web_search"]}}})
        assert p.authorize(_make_request(resource="tool", target="web_search")).allow is True
        assert p.authorize(_make_request(resource="tool", target="bash")).allow is False

    def test_model_maps_to_models(self):
        p = _provider({"user": {"models": {"allow": ["gpt-4o"]}}})
        assert p.authorize(_make_request(resource="model", target="gpt-4o")).allow is True

    def test_unknown_resource_uses_original_name(self):
        p = _provider({"user": {"custom_resource": {"allow": ["item1"]}}})
        assert p.authorize(_make_request(resource="custom_resource", target="item1")).allow is True

    def test_resource_config_missing_means_unrestricted(self):
        """If a role has no policy for a resource type, it's unrestricted."""
        p = _provider({"user": {"tools": {"allow": ["web_search"]}}})
        # No model policy configured → unrestricted
        assert p.authorize(_make_request(resource="model", target="any")).allow is True


# --- Role resolution ---


class TestRoleResolution:
    """Unknown and missing roles must fail."""

    def test_known_role_works(self):
        p = _provider({"admin": {"tools": {"allow": "*"}}, "user": {"tools": {"allow": []}}})
        assert p.authorize(_make_request(role="admin", target="bash")).allow is True
        assert p.authorize(_make_request(role="user", target="bash")).allow is False

    def test_unknown_role_raises(self):
        """Unknown role must raise ValueError, not return allow."""
        p = _provider({"admin": {"tools": {"allow": "*"}}})
        with pytest.raises(ValueError, match="Unknown role"):
            p.authorize(_make_request(role="editor", target="bash"))

    def test_missing_role_raises(self):
        """None role must raise ValueError."""
        p = _provider({"admin": {"tools": {"allow": "*"}}})
        with pytest.raises(ValueError, match="no role"):
            p.authorize(_make_request(role=None, target="bash"))

    def test_empty_string_role_raises(self):
        p = _provider({"admin": {"tools": {"allow": "*"}}})
        with pytest.raises(ValueError, match="no role"):
            p.authorize(_make_request(role="", target="bash"))


# --- filter_resources ---


class TestFilterResources:
    """Batch visibility filter."""

    def test_filter_preserves_order(self):
        p = _provider({"user": {"tools": {"allow": ["web_search", "bash", "read_file"]}}})
        result = p.filter_resources(Principal(role="user"), "tool", ["bash", "web_search", "write_file", "read_file"])
        assert result == ["bash", "web_search", "read_file"]

    def test_filter_no_duplicates_added(self):
        p = _provider({"user": {"tools": {"allow": "*"}}})
        result = p.filter_resources(Principal(role="user"), "tool", ["a", "b"])
        assert result == ["a", "b"]

    def test_filter_preserves_input_duplicates(self):
        p = _provider({"user": {"tools": {"allow": "*"}}})
        result = p.filter_resources(Principal(role="user"), "tool", ["a", "a", "b"])
        assert result == ["a", "a", "b"]

    def test_filter_does_not_modify_input(self):
        p = _provider({"user": {"tools": {"allow": ["a"]}}})
        candidates = ["a", "b", "c"]
        p.filter_resources(Principal(role="user"), "tool", candidates)
        assert candidates == ["a", "b", "c"]

    def test_filter_unrestricted_when_no_policy(self):
        p = _provider({"admin": {}})
        result = p.filter_resources(Principal(role="admin"), "tool", ["a", "b"])
        assert result == ["a", "b"]

    def test_filter_consistent_with_authorize(self):
        """filter_resources result must match per-item authorize decisions."""
        p = _provider({"user": {"tools": {"allow": "*", "deny": ["bash"]}}})
        candidates = ["bash", "web_search", "read_file", "write_file"]
        filtered = p.filter_resources(Principal(role="user"), "tool", candidates)
        per_item = [c for c in candidates if p.authorize(_make_request(target=c)).allow]
        assert filtered == per_item

    @pytest.mark.parametrize("role", [None, ""])
    def test_filter_missing_role_raises(self, role):
        """Visibility filtering propagates missing-role errors like authorize."""
        p = _provider({"user": {"tools": {"allow": "*"}}})
        with pytest.raises(ValueError, match="no role"):
            p.filter_resources(Principal(role=role), "tool", ["bash"])

    def test_filter_unknown_role_raises(self):
        """Visibility filtering propagates unknown-role errors like authorize."""
        p = _provider({"user": {"tools": {"allow": "*"}}})
        with pytest.raises(ValueError, match="Unknown role"):
            p.filter_resources(Principal(role="editor"), "tool", ["bash"])

    @pytest.mark.parametrize("resource_type", [None, ""])
    def test_filter_invalid_resource_type_raises(self, resource_type):
        p = _provider({"user": {}})
        with pytest.raises(ValueError, match="resource_type must be a non-empty string"):
            p.filter_resources(Principal(role="user"), resource_type, ["bash"])

    @pytest.mark.parametrize(
        "roles",
        [
            {"user": {}},
            {"user": {"tools": {"allow": "*"}}},
            {"user": {"tools": {"allow": ["bash"]}}},
        ],
        ids=["unrestricted", "wildcard", "allow-list"],
    )
    @pytest.mark.parametrize("candidates", [["bash", None], ["bash", ""]], ids=["null", "empty"])
    def test_filter_invalid_candidate_raises_for_every_policy_shape(self, roles, candidates):
        p = _provider(roles)
        with pytest.raises(ValueError, match=r"candidates\[1\] must be a non-empty string"):
            p.filter_resources(Principal(role="user"), "tool", candidates)

    @pytest.mark.parametrize("candidates", [None, ("bash",), "bash"])
    def test_filter_non_list_candidates_raises(self, candidates):
        p = _provider({"user": {"tools": {"allow": "*"}}})
        with pytest.raises(ValueError, match="candidates must be a list"):
            p.filter_resources(Principal(role="user"), "tool", candidates)


# --- Request validation ---


class TestRequestValidation:
    """Malformed request identifiers must fail before any allow decision."""

    @pytest.mark.parametrize(
        "roles",
        [
            {"user": {}},
            {"user": {"tools": {"allow": "*"}}},
            {"user": {"tools": {"allow": ["bash"]}}},
        ],
        ids=["unrestricted", "wildcard", "allow-list"],
    )
    @pytest.mark.parametrize("target", [None, ""], ids=["null", "empty"])
    def test_authorize_invalid_target_raises_for_every_policy_shape(self, roles, target):
        p = _provider(roles)
        with pytest.raises(ValueError, match="target must be a non-empty string"):
            p.authorize(_make_request(target=target))

    @pytest.mark.parametrize("resource", [None, ""], ids=["null", "empty"])
    def test_authorize_invalid_resource_raises(self, resource):
        p = _provider({"user": {"tools": {"allow": "*"}}})
        with pytest.raises(ValueError, match="resource must be a non-empty string"):
            p.authorize(_make_request(resource=resource))

    @pytest.mark.parametrize("target", [None, ""], ids=["null", "empty"])
    def test_aauthorize_invalid_target_matches_sync_validation(self, target):
        p = _provider({"user": {"tools": {"allow": "*"}}})
        with pytest.raises(ValueError, match="target must be a non-empty string"):
            asyncio.run(p.aauthorize(_make_request(target=target)))


# --- Sync / async parity ---


class TestSyncAsyncParity:
    def test_aauthorize_matches_authorize(self):
        p = _provider({"user": {"tools": {"allow": "*", "deny": ["bash"]}}})
        req = _make_request(target="bash")
        sync = p.authorize(req)
        async_ = asyncio.run(p.aauthorize(req))
        assert sync.allow == async_.allow
        assert sync.reasons[0].code == async_.reasons[0].code


# --- Construction validation ---


class TestConstructionValidation:
    """Invalid config must fail at construction, not at request time."""

    def test_unknown_provider_config_key_raises(self):
        with pytest.raises(ValueError, match="unknown provider config keys.*bogus"):
            RbacAuthorizationProvider(roles={"user": {}}, bogus=True)

    def test_misspelled_roles_key_raises(self):
        with pytest.raises(ValueError, match="unknown provider config keys.*rolez"):
            RbacAuthorizationProvider(rolez={"user": {}})

    def test_non_dict_roles_raises(self):
        with pytest.raises(ValueError, match="roles must be a dict"):
            RbacAuthorizationProvider(roles=["not", "a", "dict"])

    def test_non_dict_role_config_raises(self):
        with pytest.raises(ValueError, match="config must be a dict"):
            RbacAuthorizationProvider(roles={"user": "not a dict"})

    def test_non_dict_resource_policy_raises(self):
        with pytest.raises(ValueError, match="must be a dict"):
            RbacAuthorizationProvider(roles={"user": {"tools": "not a dict"}})

    def test_invalid_allow_type_raises(self):
        with pytest.raises(ValueError, match="allow must be"):
            RbacAuthorizationProvider(roles={"user": {"tools": {"allow": 42}}})

    def test_invalid_allow_string_raises(self):
        with pytest.raises(ValueError, match="allow string must be"):
            RbacAuthorizationProvider(roles={"user": {"tools": {"allow": "not_wildcard"}}})

    def test_non_string_in_allow_list_raises(self):
        with pytest.raises(ValueError, match="non-string"):
            RbacAuthorizationProvider(roles={"user": {"tools": {"allow": ["ok", 42]}}})

    def test_non_string_in_deny_list_raises(self):
        with pytest.raises(ValueError, match="non-string"):
            RbacAuthorizationProvider(roles={"user": {"tools": {"deny": ["ok", None]}}})

    def test_empty_string_in_allow_list_raises(self):
        with pytest.raises(ValueError, match="non-string or empty"):
            RbacAuthorizationProvider(roles={"user": {"tools": {"allow": ["ok", ""]}}})

    def test_invalid_deny_type_raises(self):
        with pytest.raises(ValueError, match="deny must be"):
            RbacAuthorizationProvider(roles={"user": {"tools": {"deny": 42}}})

    def test_empty_role_name_raises(self):
        with pytest.raises(ValueError, match="non-empty string"):
            RbacAuthorizationProvider(roles={"": {"tools": {"allow": "*"}}})

    def test_empty_resource_key_raises(self):
        with pytest.raises(ValueError, match="invalid resource key"):
            RbacAuthorizationProvider(roles={"user": {"": {"allow": "*"}}})

    def test_explicit_null_allow_raises(self):
        """`allow: null` must NOT be treated as missing — it's a config error."""
        with pytest.raises(ValueError, match="allow must not be null"):
            RbacAuthorizationProvider(roles={"user": {"tools": {"allow": None}}})

    def test_explicit_null_deny_raises(self):
        """`deny: null` must NOT be treated as missing — it's a config error."""
        with pytest.raises(ValueError, match="deny must not be null"):
            RbacAuthorizationProvider(roles={"user": {"tools": {"allow": "*", "deny": None}}})

    def test_unknown_policy_key_raises(self):
        """Misspelled keys (e.g. 'alow') must be rejected, not silently ignored."""
        with pytest.raises(ValueError, match="unknown policy keys"):
            RbacAuthorizationProvider(roles={"user": {"tools": {"alow": ["web_search"]}}})

    def test_unknown_policy_key_with_valid_keys_raises(self):
        """Unknown key alongside valid keys must still be rejected."""
        with pytest.raises(ValueError, match="unknown policy keys"):
            RbacAuthorizationProvider(roles={"user": {"tools": {"allow": "*", "permt": ["extra"]}}})

    def test_mixed_type_unknown_keys_raises_value_error(self):
        """Mixed-type unknown keys (e.g. str + int) must raise ValueError,
        not TypeError from sorted() comparison failure."""
        with pytest.raises(ValueError, match="unknown policy keys"):
            RbacAuthorizationProvider(roles={"user": {"tools": {1: "bad", "other": "bad"}}})


# --- Config immutability ---


class TestConfigImmutability:
    """Provider must not be affected by post-construction config mutation."""

    def test_mutating_config_after_construction_does_not_change_behavior(self):
        roles_config = {"user": {"tools": {"allow": ["bash"]}}}
        p = RbacAuthorizationProvider(roles=roles_config)
        # Mutate the original config
        roles_config["user"]["tools"]["allow"] = ["web_search"]
        roles_config["admin"] = {"tools": {"allow": "*"}}
        # Provider should still use the original compiled policy
        assert p.authorize(_make_request(target="bash")).allow is True
        assert p.authorize(_make_request(target="web_search")).allow is False
        # Unknown role added to config should not be known to provider
        with pytest.raises(ValueError, match="Unknown role"):
            p.authorize(_make_request(role="admin", target="bash"))


# --- Protocol conformance ---


class TestProtocolConformance:
    def test_rbac_is_authorization_provider(self):
        from deerflow.authz.provider import AuthorizationProvider

        assert isinstance(RbacAuthorizationProvider(roles={}), AuthorizationProvider)
