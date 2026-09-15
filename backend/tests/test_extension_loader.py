"""Tests for config-driven extension loading."""

from __future__ import annotations

import pytest

from deerflow.extensions.loader import (
    Diagnostic,
    ExtensionLoadError,
    ExtensionSpec,
    load_extensions,
)
from extension_test_fixtures import demo_extensions

_FIXTURE = "extension_test_fixtures.demo_extensions"


@pytest.fixture(autouse=True)
def _reset_fixture_state():
    demo_extensions.INSTALLED.clear()
    yield
    demo_extensions.INSTALLED.clear()


def test_no_specs_yields_empty_result():
    loaded, diagnostics = load_extensions([])
    assert diagnostics == []
    assert loaded.has_middleware_contributors is False


def test_host_disabled_required_extension_is_skipped_before_resolution(monkeypatch):
    def _must_not_resolve(path: str):
        raise AssertionError(f"disabled extension was resolved: {path}")

    monkeypatch.setattr("deerflow.extensions.loader.resolve_variable", _must_not_resolve)

    loaded, diagnostics = load_extensions([ExtensionSpec(use="missing_extension:install", enabled=False, required=True)])

    assert diagnostics == []
    assert loaded.has_middleware_contributors is False


def test_manager_metadata_is_accepted_without_reaching_the_install_hook():
    spec = ExtensionSpec(
        name="demo",
        package="deerflow-extension-demo",
        use=f"{_FIXTURE}:install_ok",
        enabled=False,
    )

    assert spec.name == "demo"
    assert spec.package == "deerflow-extension-demo"


def test_successful_install_registers_and_attributes():
    spec = ExtensionSpec(use=f"{_FIXTURE}:install_ok")
    loaded, diagnostics = load_extensions([spec])
    assert diagnostics == []
    assert demo_extensions.INSTALLED == ["ok"]
    assert loaded.middleware_contributors[0][0] == f"{_FIXTURE}:install_ok"


def test_config_block_is_passed_through_verbatim():
    spec = ExtensionSpec(use=f"{_FIXTURE}:install_reads_config", config={"mode": "fast"})
    load_extensions([spec])
    assert demo_extensions.INSTALLED == ["config:fast"]


def test_disabled_extension_registers_nothing():
    spec = ExtensionSpec(use=f"{_FIXTURE}:install_disabled", config={"enabled": False})
    loaded, diagnostics = load_extensions([spec])
    assert diagnostics == []
    assert loaded.has_middleware_contributors is False


def test_load_order_follows_config_order():
    specs = [
        ExtensionSpec(use=f"{_FIXTURE}:install_ok"),
        ExtensionSpec(use=f"{_FIXTURE}:install_stamped"),
    ]
    load_extensions(specs)
    assert demo_extensions.INSTALLED == ["ok", "stamped"]


def test_unresolvable_entry_point_is_skipped_with_an_error_diagnostic():
    specs = [
        ExtensionSpec(use="extension_test_fixtures.demo_extensions:does_not_exist"),
        ExtensionSpec(use=f"{_FIXTURE}:install_ok"),
    ]
    loaded, diagnostics = load_extensions(specs)
    assert [d.level for d in diagnostics] == ["error"]
    assert "does_not_exist" in diagnostics[0].source
    assert demo_extensions.INSTALLED == ["ok"], "a broken extension must not stop the rest"


def test_non_callable_entry_point_is_rejected():
    spec = ExtensionSpec(use=f"{_FIXTURE}:NOT_CALLABLE")
    loaded, diagnostics = load_extensions([spec])
    assert diagnostics[0].level == "error"
    assert "callable" in diagnostics[0].message


def test_install_failure_rolls_back_partial_registration():
    specs = [
        ExtensionSpec(use=f"{_FIXTURE}:install_partial_then_raise"),
        ExtensionSpec(use=f"{_FIXTURE}:install_ok"),
    ]
    loaded, diagnostics = load_extensions(specs)
    assert diagnostics[0].level == "error"
    assert "boom" in diagnostics[0].message
    sources = {source for source, _ in loaded.middleware_contributors}
    assert sources == {f"{_FIXTURE}:install_ok"}
    assert len(loaded.middleware_contributors) == 1, "rollback must clear every partial registration"
    assert loaded.task_lifecycle == (), "rollback must clear partial lifecycle registrations too"
    assert loaded.system_model_observers == ()
    assert loaded.services == ()
    assert loaded.routers == ()


def test_rollback_does_not_remove_a_different_specs_registrations_sharing_the_same_use():
    """Two specs may legitimately share `use` with different config (e.g. the
    same extension mounted twice with different settings). Rollback on the
    second's install failure must be positional, not keyed by `use` — it must
    not erase the first instance's already-successful registrations just
    because they share a source string."""
    specs = [
        ExtensionSpec(use=f"{_FIXTURE}:install_shared_use", config={"label": "first"}),
        ExtensionSpec(use=f"{_FIXTURE}:install_shared_use", config={"label": "second", "fail": True}),
    ]
    loaded, diagnostics = load_extensions(specs)
    assert [d.level for d in diagnostics] == ["error"]
    assert "boom-shared" in diagnostics[0].message
    assert len(loaded.middleware_contributors) == 1
    source, contributor = loaded.middleware_contributors[0]
    assert source == f"{_FIXTURE}:install_shared_use"
    assert contributor.tag == "shared:first"


def test_required_extension_failure_aborts_startup():
    spec = ExtensionSpec(use=f"{_FIXTURE}:install_partial_then_raise", required=True)
    with pytest.raises(ExtensionLoadError):
        load_extensions([spec])


def test_required_unresolvable_extension_aborts_startup():
    spec = ExtensionSpec(use="nope.nothing:here", required=True)
    with pytest.raises(ExtensionLoadError):
        load_extensions([spec])


def test_incompatible_declared_api_is_refused_with_actionable_message():
    spec = ExtensionSpec(use=f"{_FIXTURE}:install_future_api")
    loaded, diagnostics = load_extensions([spec])
    assert diagnostics[0].level == "error"
    assert "99.0" in diagnostics[0].message
    assert "pip install" in diagnostics[0].message
    assert demo_extensions.INSTALLED == [], "an incompatible extension must not run"


def test_optional_extension_with_non_string_api_marker_is_skipped_with_a_diagnostic(monkeypatch):
    monkeypatch.setattr(demo_extensions.install_ok, "__deerflow_api__", 101, raising=False)
    spec = ExtensionSpec(use=f"{_FIXTURE}:install_ok")

    loaded, diagnostics = load_extensions([spec])

    assert loaded.has_middleware_contributors is False
    assert demo_extensions.INSTALLED == [], "an invalid API marker must be rejected before install()"
    assert len(diagnostics) == 1
    assert diagnostics[0].level == "error"
    assert diagnostics[0].source == spec.use
    assert "invalid extension-api version marker" in diagnostics[0].message
    assert "int" in diagnostics[0].message


def test_required_extension_with_non_string_iterable_api_marker_fails_closed(monkeypatch):
    class _IterableAPIMarker:
        def split(self, separator: str) -> list[object]:
            return [object()]

        def __str__(self) -> str:
            return "non-string iterable marker"

    monkeypatch.setattr(
        demo_extensions.install_ok,
        "__deerflow_api__",
        _IterableAPIMarker(),
        raising=False,
    )
    spec = ExtensionSpec(
        use=f"{_FIXTURE}:install_ok",
        required=True,
    )

    with pytest.raises(ExtensionLoadError, match="declares invalid api marker"):
        load_extensions([spec])

    assert demo_extensions.INSTALLED == [], "an invalid API marker must be rejected before install()"


def test_optional_extension_with_unrenderable_api_marker_still_returns_a_diagnostic(monkeypatch):
    class _UnrenderableAPIMarker:
        def __str__(self) -> str:
            raise RuntimeError("API marker string rendering exploded")

    monkeypatch.setattr(
        demo_extensions.install_ok,
        "__deerflow_api__",
        _UnrenderableAPIMarker(),
        raising=False,
    )
    spec = ExtensionSpec(use=f"{_FIXTURE}:install_ok")

    loaded, diagnostics = load_extensions([spec])

    assert loaded.has_middleware_contributors is False
    assert demo_extensions.INSTALLED == []
    assert len(diagnostics) == 1
    assert diagnostics[0].level == "error"
    assert "invalid extension-api version marker" in diagnostics[0].message
    assert "_UnrenderableAPIMarker" in diagnostics[0].message


@pytest.mark.parametrize("required", [False, True])
def test_extension_api_marker_getter_failure_obeys_required_policy(monkeypatch, required):
    class _ExplodingMarkerInstall:
        @property
        def __deerflow_api__(self):
            raise RuntimeError("API marker getter exploded")

        def __call__(self, registry, config):
            raise AssertionError("install must not run after marker inspection fails")

    monkeypatch.setattr(
        "deerflow.extensions.loader.resolve_variable",
        lambda path: _ExplodingMarkerInstall(),
    )
    spec = ExtensionSpec(use="hostile_extension:install", required=required)

    if required:
        with pytest.raises(ExtensionLoadError, match="could not inspect api marker"):
            load_extensions([spec])
        return

    loaded, diagnostics = load_extensions([spec])
    assert loaded.has_middleware_contributors is False
    assert len(diagnostics) == 1
    assert "could not inspect extension-api version marker" in diagnostics[0].message


def test_string_subclass_api_marker_cannot_break_incompatibility_diagnostics(monkeypatch):
    class _HostileString(str):
        def split(self, separator: str):
            raise RuntimeError("API marker split exploded")

        def __str__(self) -> str:
            raise RuntimeError("API marker string rendering exploded")

        def __format__(self, format_spec: str) -> str:
            raise RuntimeError("API marker formatting exploded")

    monkeypatch.setattr(
        demo_extensions.install_ok,
        "__deerflow_api__",
        _HostileString("99.0"),
        raising=False,
    )
    spec = ExtensionSpec(use=f"{_FIXTURE}:install_ok")

    loaded, diagnostics = load_extensions([spec])

    assert loaded.has_middleware_contributors is False
    assert demo_extensions.INSTALLED == []
    assert len(diagnostics) == 1
    assert "99.0" in diagnostics[0].message


def test_compatible_string_subclass_api_marker_can_load(monkeypatch):
    class _HostileString(str):
        def split(self, separator: str):
            raise RuntimeError("API marker split exploded")

        def __str__(self) -> str:
            raise RuntimeError("API marker string rendering exploded")

        def __format__(self, format_spec: str) -> str:
            raise RuntimeError("API marker formatting exploded")

    monkeypatch.setattr(
        demo_extensions.install_ok,
        "__deerflow_api__",
        _HostileString("0.2.0"),
        raising=False,
    )

    loaded, diagnostics = load_extensions([ExtensionSpec(use=f"{_FIXTURE}:install_ok")])

    assert diagnostics == []
    assert loaded.has_middleware_contributors is True
    assert demo_extensions.INSTALLED == ["ok"]


def test_newer_minor_declared_api_is_refused():
    """Before 1.0, minors carry no compatibility promise: an extension written
    against 0.2 may use contracts a 0.1 host does not implement, and the host
    must refuse it with an actionable message."""
    spec = ExtensionSpec(use=f"{_FIXTURE}:install_newer_minor_api")
    loaded, diagnostics = load_extensions([spec])
    assert diagnostics[0].level == "error"
    assert "0.2" in diagnostics[0].message
    assert "pip install" in diagnostics[0].message
    assert demo_extensions.INSTALLED == [], "a newer-minor extension must not run on an older host"


def test_newer_minor_required_extension_aborts_startup():
    spec = ExtensionSpec(use=f"{_FIXTURE}:install_newer_minor_api", required=True)
    with pytest.raises(ExtensionLoadError):
        load_extensions([spec])


def test_compatible_declared_api_loads():
    spec = ExtensionSpec(use=f"{_FIXTURE}:install_stamped")
    loaded, diagnostics = load_extensions([spec])
    assert diagnostics == []
    assert demo_extensions.INSTALLED == ["stamped"]
    assert loaded.has_task_lifecycle is True
    assert loaded.task_lifecycle[0][0] == f"{_FIXTURE}:install_stamped"


def test_compatible_follows_semver_windows():
    """0.x: minors may break — the window is same major.minor with patches
    additive (host >= declared). From 1.0 on: contracts only grow within a
    major. Comparisons are numeric (1.10 > 1.9), not lexicographic."""
    from deerflow.extensions.loader import _compatible

    # 0.x window: same major.minor, patch-level growth only.
    assert _compatible("0.1", "0.1")
    assert _compatible("0.1", "0.1.1"), "patch growth stays compatible"
    assert not _compatible("0.1.1", "0.1"), "a newer patch declaration exceeds what the host provides"
    assert not _compatible("0.2", "0.1"), "0.x minors may break: a 0.1 host must refuse 0.2 extensions"
    assert not _compatible("0.1", "0.2"), "0.x minors promise nothing in the other direction either"

    # 1.x+ window: same major, contracts only grow.
    assert _compatible("1.0", "1.0")
    assert _compatible("1.0", "1.1"), "a newer host still provides everything a 1.0 extension declared"
    assert _compatible("1.9", "1.10"), "minor comparison is numeric, not lexicographic"
    assert not _compatible("1.1", "1.0"), "the 1.0 host lacks the 1.1 contract additions"
    assert not _compatible("1.10", "1.9")
    assert not _compatible("1.0.1", "1.0"), "even a newer patch declaration exceeds what the host provides"
    assert not _compatible("2.0", "1.5"), "major mismatch"
    assert not _compatible("1.0", "2.0"), "major mismatch"
    assert not _compatible("not-a-version", "1.0"), "unparseable versions are refused, not waved through"


def test_undeclared_api_is_allowed():
    """The decorator is optional; pip constraints remain the primary gate."""
    spec = ExtensionSpec(use=f"{_FIXTURE}:install_ok")
    _, diagnostics = load_extensions([spec])
    assert diagnostics == []


def test_a_successful_load_is_reported(caplog):
    """Every other branch is failure-only, so without this line an operator has
    no way to tell a clean load from a `plugins:` block the host never read."""
    with caplog.at_level("INFO", logger="deerflow.extensions.loader"):
        load_extensions([ExtensionSpec(use=f"{_FIXTURE}:install_ok")])

    assert f"Extensions loaded: 1/1 ({_FIXTURE}:install_ok)" in caplog.text


def test_the_report_counts_skipped_extensions_apart_from_loaded_ones(caplog):
    specs = [
        ExtensionSpec(use=f"{_FIXTURE}:install_ok"),
        ExtensionSpec(use="does.not.exist:install"),
    ]
    with caplog.at_level("INFO", logger="deerflow.extensions.loader"):
        load_extensions(specs)

    assert f"Extensions loaded: 1/2 ({_FIXTURE}:install_ok)" in caplog.text


def test_an_all_failed_load_reports_none_rather_than_an_empty_list(caplog):
    with caplog.at_level("INFO", logger="deerflow.extensions.loader"):
        load_extensions([ExtensionSpec(use="does.not.exist:install")])

    assert "Extensions loaded: 0/1 (none)" in caplog.text


def test_no_configured_plugins_stays_off_the_info_log(caplog):
    """The default state for nearly every deployment; a line here is boot noise."""
    with caplog.at_level("INFO", logger="deerflow.extensions.loader"):
        load_extensions([])

    assert "Extensions loaded" not in caplog.text


def test_diagnostic_helpers_set_level():
    assert Diagnostic.error("s", "m").level == "error"
    assert Diagnostic.warning("s", "m").level == "warning"
    assert Diagnostic.info("s", "m").level == "info"
    assert Diagnostic.debug("s", "m").level == "debug"


def test_host_registry_satisfies_the_public_contract():
    """Extensions annotate install(registry: ExtensionRegistry, ...) against
    the contract package alone; the host's concrete registry must satisfy that
    Protocol, or every correctly-annotated extension is lying about its types."""
    from deerflow_extension_api import ExtensionRegistry as ContractRegistry

    from deerflow.extensions.registry import ExtensionRegistry as HostRegistry

    assert isinstance(HostRegistry(), ContractRegistry)


class TestTablePrefixRegistration:
    """A spec's ``table_prefix`` must reach alembic's exclusion filter.

    ``EXTENSION_TABLE_PREFIXES`` is module-level mutable state shared with
    ``_env_filters``, so every test here restores it -- a test that registers
    a prefix and leaves it registered would poison every later test in the
    process, including the filter's own suite.
    """

    def setup_method(self):
        from deerflow.persistence.migrations import _env_filters

        self._saved = set(_env_filters.EXTENSION_TABLE_PREFIXES)

    def teardown_method(self):
        from deerflow.persistence.migrations import _env_filters

        _env_filters.EXTENSION_TABLE_PREFIXES.clear()
        _env_filters.EXTENSION_TABLE_PREFIXES.update(self._saved)

    def test_a_declared_prefix_is_registered_with_the_migration_filter(self):
        from deerflow.persistence.migrations._env_filters import include_object

        spec = ExtensionSpec(use=f"{_FIXTURE}:install_ok", table_prefix="ext_")
        load_extensions([spec])

        assert include_object(None, "ext_events", "table", True, None) is False

    def test_no_declared_prefix_registers_nothing(self):
        from deerflow.persistence.migrations import _env_filters

        spec = ExtensionSpec(use=f"{_FIXTURE}:install_ok")
        load_extensions([spec])

        assert _env_filters.EXTENSION_TABLE_PREFIXES == self._saved

    def test_a_disabled_specs_prefix_is_still_registered(self):
        """Tables from a previously-enabled run may still be in the database;
        disabling the extension must not make autogenerate reflect them."""
        from deerflow.persistence.migrations._env_filters import include_object

        spec = ExtensionSpec(use=f"{_FIXTURE}:install_ok", enabled=False, table_prefix="ext_")
        load_extensions([spec])

        assert include_object(None, "ext_events", "table", True, None) is False

    def test_a_failing_specs_prefix_is_still_registered(self):
        """A broken install() this run doesn't retroactively delete tables a
        prior successful run already created."""
        from deerflow.persistence.migrations._env_filters import include_object

        spec = ExtensionSpec(use=f"{_FIXTURE}:install_partial_then_raise", table_prefix="ext_")
        load_extensions([spec])

        assert include_object(None, "ext_events", "table", True, None) is False

    def test_a_prefix_that_collides_with_a_host_table_aborts_loading(self):
        """A typo such as table_prefix: "run" would silently stop alembic from
        managing the host's own `runs` table. That must abort startup loudly
        rather than degrade the whole host's autogenerate coverage, regardless
        of `required` -- the corruption is not scoped to this one extension."""
        spec = ExtensionSpec(use=f"{_FIXTURE}:install_ok", required=False, table_prefix="run")

        with pytest.raises(ExtensionLoadError, match="runs"):
            load_extensions([spec])

    def test_an_empty_prefix_is_rejected_at_config_load(self):
        """Omit the key to declare no prefix; "" is not a way to spell that.

        The declaration is read by two processes that cannot both be right
        about an empty string: the loader's ``if spec.table_prefix:`` would
        treat it as "no prefix", while a reader taking it literally has a
        prefix that matches every table name. Rejecting it here means the
        question is never asked twice — and it is asked in the process an
        operator is actually looking at when the Gateway refuses to start.
        """
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="table_prefix"):
            ExtensionSpec(use=f"{_FIXTURE}:install_ok", table_prefix="")

    def test_omitting_the_key_remains_the_way_to_declare_no_prefix(self):
        assert ExtensionSpec(use=f"{_FIXTURE}:install_ok").table_prefix is None
        assert ExtensionSpec(use=f"{_FIXTURE}:install_ok", table_prefix=None).table_prefix is None
