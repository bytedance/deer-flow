"""Tests for reflection resolvers."""

import pytest

from deerflow.reflection import resolvers
from deerflow.reflection.resolvers import resolve_variable


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


def test_resolve_variable_empty_attribute_reports_format_guidance():
    """A trailing colon (empty attribute) is a typo, not a missing attribute (#7015)."""
    with pytest.raises(ImportError) as exc_info:
        resolve_variable("json:")

    message = str(exc_info.value)
    assert "doesn't look like a variable path" in message
    assert "does not define" not in message


def test_resolve_variable_extra_colon_reports_format_guidance():
    """An extra colon is a typo, not a dependency to install (#7015)."""
    with pytest.raises(ImportError) as exc_info:
        resolve_variable("json:loads:extra")

    message = str(exc_info.value)
    assert "doesn't look like a variable path" in message
    assert "Missing dependency" not in message
    assert "uv add" not in message


def test_resolve_variable_empty_module_reports_format_guidance():
    """A leading colon (empty module) is a typo, not a missing module (#7015)."""
    with pytest.raises(ImportError) as exc_info:
        resolve_variable(":loads")

    message = str(exc_info.value)
    assert "doesn't look like a variable path" in message
