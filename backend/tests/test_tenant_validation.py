"""Tests for tenant ID validation."""

import pytest

from deerflow.config.tenant import (
    TENANT_ID_PATTERN,
    _DEFAULT_TENANT_ID,
    get_current_tenant_id,
    reset_tenant_id,
    set_current_tenant_id,
    validate_tenant_id,
)


class TestTenantIdPattern:
    def test_valid_tenant_ids(self):
        valid = ["default", "acme", "my-org", "tenant-123", "a", "ab", "test-tenant"]
        for tid in valid:
            assert TENANT_ID_PATTERN.match(tid), f"Should accept: {tid!r}"

    def test_invalid_tenant_ids(self):
        invalid = [
            "../escape",
            "has space",
            "has/slash",
            "has\\backslash",
            "",
            "with.dot",
            "with_underscore",
        ]
        for tid in invalid:
            assert not TENANT_ID_PATTERN.match(tid), f"Should reject: {tid!r}"


class TestValidateTenantId:
    def test_valid_passes_through(self):
        assert validate_tenant_id("acme") == "acme"
        assert validate_tenant_id("default") == "default"

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="Invalid tenant ID"):
            validate_tenant_id("../escape")
        with pytest.raises(ValueError, match="Invalid tenant ID"):
            validate_tenant_id("has space")

    def test_non_string_raises(self):
        with pytest.raises(ValueError, match="must be a string"):
            validate_tenant_id(123)
        with pytest.raises(ValueError, match="must be a string"):
            validate_tenant_id(None)


class TestContextVar:
    def test_default_is_default(self):
        assert get_current_tenant_id() == _DEFAULT_TENANT_ID

    def test_set_and_get(self):
        token = set_current_tenant_id("acme")
        try:
            assert get_current_tenant_id() == "acme"
        finally:
            reset_tenant_id(token)

    def test_reset_restores_previous(self):
        token = set_current_tenant_id("acme")
        assert get_current_tenant_id() == "acme"
        reset_tenant_id(token)
        assert get_current_tenant_id() == _DEFAULT_TENANT_ID

    def test_nested_set(self):
        outer = set_current_tenant_id("outer")
        try:
            assert get_current_tenant_id() == "outer"
            inner = set_current_tenant_id("inner")
            try:
                assert get_current_tenant_id() == "inner"
            finally:
                reset_tenant_id(inner)
            assert get_current_tenant_id() == "outer"
        finally:
            reset_tenant_id(outer)
        assert get_current_tenant_id() == _DEFAULT_TENANT_ID
