"""Tests for tenant middleware in the Gateway app."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deerflow.config.tenant import (
    _DEFAULT_TENANT_ID,
    get_current_tenant_id,
    set_current_tenant_id,
    validate_tenant_id,
)


class TestMiddlewareLogic:
    """Test the tenant middleware extraction/validation/setting logic directly.

    The middleware itself is a simple function in app.py; these tests
    exercise the same logic without spinning up a full FastAPI app.
    """

    def test_missing_header_defaults_to_default(self):
        tenant_id = "default"
        validate_tenant_id(tenant_id)
        token = set_current_tenant_id(tenant_id)
        try:
            assert get_current_tenant_id() == _DEFAULT_TENANT_ID
        finally:
            from deerflow.config.tenant import reset_tenant_id

            reset_tenant_id(token)

    def test_valid_header_sets_tenant(self):
        tenant_id = "acme-corp"
        validate_tenant_id(tenant_id)
        token = set_current_tenant_id(tenant_id)
        try:
            assert get_current_tenant_id() == "acme-corp"
        finally:
            from deerflow.config.tenant import reset_tenant_id

            reset_tenant_id(token)

    def test_invalid_header_raises(self):
        with pytest.raises(ValueError, match="Invalid tenant ID"):
            validate_tenant_id("../malicious")

    def test_header_with_special_chars_raises(self):
        for bad in ["has space", "has/slash", "with.dot"]:
            with pytest.raises(ValueError, match="Invalid tenant ID"):
                validate_tenant_id(bad)

    def test_non_string_header_raises(self):
        with pytest.raises(ValueError, match="must be a string"):
            validate_tenant_id(123)


class TestContextVarLifecycle:
    def test_nested_tenants_restore_correctly(self):
        outer = set_current_tenant_id("outer-org")
        try:
            assert get_current_tenant_id() == "outer-org"
            inner = set_current_tenant_id("inner-org")
            try:
                assert get_current_tenant_id() == "inner-org"
            finally:
                from deerflow.config.tenant import reset_tenant_id

                reset_tenant_id(inner)
            assert get_current_tenant_id() == "outer-org"
        finally:
            from deerflow.config.tenant import reset_tenant_id

            reset_tenant_id(outer)
        assert get_current_tenant_id() == _DEFAULT_TENANT_ID

    def test_default_is_restored_after_reset(self):
        token = set_current_tenant_id("temp-org")
        try:
            assert get_current_tenant_id() == "temp-org"
        finally:
            from deerflow.config.tenant import reset_tenant_id

            reset_tenant_id(token)
        assert get_current_tenant_id() == _DEFAULT_TENANT_ID
