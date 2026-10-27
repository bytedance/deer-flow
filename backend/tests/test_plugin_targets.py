"""Composite plugin authorization targets: one encoder, one validator.

The three constructors are the only sanctioned producers of the strings a
plugin decision is keyed on, so these tests pin the charsets, the cross-kind
shape, and the drift guard that keeps the Python copies of the host's
namespace rule (authz, extension-api, plugin settings) from diverging.
"""

from __future__ import annotations

import pytest

from deerflow.authz.plugin_targets import (
    MANAGEMENT_READ_PART,
    MANAGEMENT_WRITE_PART,
    PluginTargetError,
    plugin_action_target,
    plugin_management_target,
    plugin_page_target,
)

# One sample set reused for every copy of the namespace rule, so a divergence
# between them fails here instead of at runtime.
VALID_NAMESPACES = [
    "a",
    "acme.reports",
    "community.check",
    "a1.b-c_d",
    "a" * 96,
]
INVALID_NAMESPACES = [
    "",
    "A",
    "Acme.Reports",
    "1a",
    ".a",
    "-a",
    "_a",
    "a/b",
    "a b",
    "a" * 97,
    "aé",
]

VALID_ACTION_NAMES = ["reports", "ex-port", "a_1", "x" * 64]
INVALID_ACTION_NAMES = ["", "Reports", "1a", "a.b", "a b", "a" * 65]

VALID_SURFACE_IDS = ["reports", "my-page", "a1", "x" * 64]
INVALID_SURFACE_IDS = ["", "Reports", "1a", "my_page", "a.b", "a" * 65, "-page"]


# --- Composing -----------------------------------------------------------------


@pytest.mark.parametrize("namespace", VALID_NAMESPACES)
def test_composes_namespace_scoped_targets(namespace: str):
    assert plugin_action_target(namespace, "reports") == f"{namespace}/reports"
    assert plugin_page_target(namespace, "reports") == f"{namespace}/reports"
    assert plugin_management_target(namespace, MANAGEMENT_READ_PART) == f"{namespace}/permissions.read"
    assert plugin_management_target(namespace, MANAGEMENT_WRITE_PART) == f"{namespace}/permissions.write"


def test_management_part_constants_are_the_documented_targets():
    assert MANAGEMENT_READ_PART == "permissions.read"
    assert MANAGEMENT_WRITE_PART == "permissions.write"


def test_read_and_write_are_distinct_targets_on_one_resource():
    """The built-in provider ignores ``action``, so the target must differ."""
    assert plugin_management_target("acme.reports", MANAGEMENT_READ_PART) != plugin_management_target("acme.reports", MANAGEMENT_WRITE_PART)


def test_action_and_page_targets_are_byte_identical_for_one_declared_name():
    """Documented ambiguity: readers must key on ``(resource, target)``."""
    assert plugin_action_target("acme.reports", "reports") == plugin_page_target("acme.reports", "reports")


# --- Rejecting -----------------------------------------------------------------


@pytest.mark.parametrize("namespace", INVALID_NAMESPACES)
def test_every_constructor_rejects_an_invalid_namespace(namespace: str):
    for build in (
        lambda: plugin_action_target(namespace, "reports"),
        lambda: plugin_page_target(namespace, "reports"),
        lambda: plugin_management_target(namespace, MANAGEMENT_READ_PART),
    ):
        with pytest.raises(PluginTargetError):
            build()


@pytest.mark.parametrize("action_name", INVALID_ACTION_NAMES)
def test_action_constructor_rejects_an_invalid_action_name(action_name: str):
    with pytest.raises(PluginTargetError):
        plugin_action_target("acme.reports", action_name)


@pytest.mark.parametrize("surface_id", INVALID_SURFACE_IDS)
def test_page_constructor_rejects_an_invalid_surface_id(surface_id: str):
    with pytest.raises(PluginTargetError):
        plugin_page_target("acme.reports", surface_id)


@pytest.mark.parametrize("part", ["permissions", "read", "permissions.read ", "", "PERMISSIONS.READ", "permissions.write.extra", None, 1])
def test_management_constructor_accepts_only_the_two_documented_parts(part):
    with pytest.raises(PluginTargetError):
        plugin_management_target("acme.reports", part)


@pytest.mark.parametrize("namespace", VALID_NAMESPACES)
@pytest.mark.parametrize("action_name", VALID_ACTION_NAMES)
def test_valid_components_are_never_rejected(namespace: str, action_name: str):
    assert plugin_action_target(namespace, action_name).startswith(f"{namespace}/")


def test_target_error_is_a_value_error():
    """Callers that only catch ``ValueError`` still fail loudly."""
    assert issubclass(PluginTargetError, ValueError)


def test_action_charset_is_not_reused_for_surface_ids():
    """An underscore is legal in an action name and illegal in a surface id."""
    assert plugin_action_target("acme.reports", "my_page").endswith("/my_page")
    with pytest.raises(PluginTargetError):
        plugin_page_target("acme.reports", "my_page")


def test_namespace_charset_is_not_reused_for_parts():
    """A dot is legal in a namespace and illegal in an action name."""
    assert plugin_action_target("acme.reports", "reports").startswith("acme.reports/")
    with pytest.raises(PluginTargetError):
        plugin_action_target("acme.reports", "report.v2")


# --- Drift guard ---------------------------------------------------------------


def _accepted_by_plugin_targets(namespace: str) -> bool:
    try:
        plugin_action_target(namespace, "reports")
    except PluginTargetError:
        return False
    return True


def _accepted_by_extension_api(namespace: str) -> bool:
    from deerflow_extension_api.auth import _require_plugin_namespace

    try:
        _require_plugin_namespace(namespace)
    except ValueError:
        return False
    return True


def _accepted_by_plugin_settings(namespace: str) -> bool:
    from deerflow_extension_api.settings import SettingsContribution, SettingsField

    from deerflow.config.plugin_settings import validate_contribution

    contribution = SettingsContribution(
        namespace=namespace,
        title="Drift probe",
        fields=(SettingsField("enabled", "Enabled", "boolean", True),),
    )
    try:
        validate_contribution(contribution)
    except ValueError:
        return False
    return True


def _accepted_by_tool_provenance(namespace: str) -> bool:
    from deerflow.tools import tool_provenance

    return tool_provenance._NAMESPACE_RE.fullmatch(namespace) is not None


@pytest.mark.parametrize("namespace", [*VALID_NAMESPACES, *INVALID_NAMESPACES])
def test_every_namespace_rule_copy_agrees(namespace: str):
    expected = namespace in VALID_NAMESPACES
    assert _accepted_by_plugin_targets(namespace) is expected
    assert _accepted_by_extension_api(namespace) is expected
    assert _accepted_by_plugin_settings(namespace) is expected
    assert _accepted_by_tool_provenance(namespace) is expected
