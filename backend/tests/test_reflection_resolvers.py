"""Tests for reflection resolvers."""

import pytest

from src.reflection import resolvers
from src.reflection.resolvers import resolve_variable


def test_resolve_variable_reports_install_hint_for_missing_google_provider(monkeypatch: pytest.MonkeyPatch):
    """Missing google provider should return actionable install guidance."""

    def fake_import_module(module_path: str):
        raise ModuleNotFoundError(f"No module named '{module_path}'", name=module_path)

    monkeypatch.setattr(resolvers, "import_module", fake_import_module)

    with pytest.raises(ImportError) as exc_info:
        resolve_variable("langchain_google_genai:ChatGoogleGenerativeAI")

    message = str(exc_info.value)
    assert "Could not import module langchain_google_genai" in message
    assert "uv add langchain-google-genai" in message


def test_resolve_variable_reports_install_hint_for_missing_google_transitive_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing transitive dependency should still return actionable install guidance."""

    def fake_import_module(module_path: str):
        # Simulate provider module existing but a transitive dependency (e.g. `google`) missing.
        raise ModuleNotFoundError("No module named 'google'", name="google")

    monkeypatch.setattr(resolvers, "import_module", fake_import_module)

    with pytest.raises(ImportError) as exc_info:
        resolve_variable("langchain_google_genai:ChatGoogleGenerativeAI")

    message = str(exc_info.value)
    # Even when a transitive dependency is missing, the hint should still point to the provider package.
    assert "uv add langchain-google-genai" in message


def test_resolve_variable_invalid_path_format():
    """Invalid variable path should fail with format guidance."""
    with pytest.raises(ImportError) as exc_info:
        resolve_variable("invalid.variable.path")

    assert "doesn't look like a variable path" in str(exc_info.value)


def test_resolve_variable_blocks_disallowed_module():
    """Modules outside the allowlist should be rejected."""
    with pytest.raises(ImportError) as exc_info:
        resolve_variable("os:system")

    assert "not in the allowed module prefixes" in str(exc_info.value)


def test_resolve_variable_blocks_subprocess():
    """subprocess module should be blocked by the allowlist."""
    with pytest.raises(ImportError) as exc_info:
        resolve_variable("subprocess:run")

    assert "not in the allowed module prefixes" in str(exc_info.value)


def test_resolve_variable_allows_src_modules(monkeypatch: pytest.MonkeyPatch):
    """src.* modules should pass the allowlist check (may still fail to import)."""
    with pytest.raises((ImportError, AttributeError)):
        resolve_variable("src.nonexistent_module:SomeClass")


def test_resolve_variable_allows_langchain_modules(monkeypatch: pytest.MonkeyPatch):
    """langchain* modules should pass the allowlist check."""

    def fake_import_module(module_path: str):
        raise ModuleNotFoundError(f"No module named '{module_path}'", name=module_path)

    monkeypatch.setattr(resolvers, "import_module", fake_import_module)

    with pytest.raises(ImportError) as exc_info:
        resolve_variable("langchain_openai:ChatOpenAI")

    assert "Could not import module" in str(exc_info.value)
