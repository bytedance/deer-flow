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


def test_resolve_variable_rejects_an_empty_variable_name():
    """A trailing colon is a malformed path, not a missing attribute.

    ``"json:"`` used to reach ``getattr(module, "")`` and report
    ``Module json does not define a  attribute/class`` -- a blank name in the
    middle of the sentence, which reads as a broken message rather than as the
    path mistake it is.
    """
    with pytest.raises(ImportError) as exc_info:
        resolve_variable("json:")

    message = str(exc_info.value)
    assert "doesn't look like a variable path" in message


def test_resolve_variable_rejects_extra_colons_instead_of_blaming_a_dependency():
    """``"json:loads:extra"`` used to be diagnosed as a missing dependency.

    ``rsplit(":", 1)`` split into module ``"json:loads"`` and reported
    ``Missing dependency 'json:loads'`` with an ``uv add json:loads`` hint --
    advice that cannot work, because the colon is a typo rather than part of a
    distribution name.
    """
    with pytest.raises(ImportError) as exc_info:
        resolve_variable("json:loads:extra")

    message = str(exc_info.value)
    assert "doesn't look like a variable path" in message
    assert "uv add" not in message


def test_resolve_variable_rejects_a_relative_module_path():
    """A leading dot would escape the ImportError contract entirely.

    ``import_module(".foo")`` raises ``TypeError``, not ``ImportError``, so a
    provider/extension/middleware loader that catches ``ImportError`` crashed
    instead of reporting a bad path. These paths are absolute by construction.
    """
    with pytest.raises(ImportError) as exc_info:
        resolve_variable(".foo:bar")

    message = str(exc_info.value)
    assert "doesn't look like a variable path" in message


def test_resolve_variable_rejects_an_empty_module_half():
    """``":attr"`` used to reach ``import_module("")`` and surface ValueError."""
    with pytest.raises(ImportError) as exc_info:
        resolve_variable(":attr")

    message = str(exc_info.value)
    assert "doesn't look like a variable path" in message


def test_resolve_variable_rejects_a_trailing_dot_in_the_module_path():
    """``"json.:attr"`` used to advertise a distribution named ``json.``.

    It stays inside the ImportError contract, so the failure mode is the
    advice: the missing-dependency branch proposes ``uv add json.``, which
    cannot work because a dotted module path never ends in a dot.
    """
    with pytest.raises(ImportError) as exc_info:
        resolve_variable("json.:attr")

    message = str(exc_info.value)
    assert "doesn't look like a variable path" in message
    assert "uv add" not in message


def test_resolve_variable_rejects_stray_whitespace_in_the_module_path():
    """A space inside the module half is invisible in the rendered hint.

    ``"json :loads"`` (a pasted sentence fragment) reached the
    missing-dependency branch and suggested ``uv add json `` -- the trailing
    space is the typo and is not visible in the message.
    """
    with pytest.raises(ImportError) as exc_info:
        resolve_variable("json :loads")

    message = str(exc_info.value)
    assert "doesn't look like a variable path" in message
    assert "uv add" not in message


def test_resolve_variable_rejects_surrounding_whitespace_in_the_path():
    """Leading/trailing space around the whole path is the same mistake."""
    for path in (" json:attr", "json:attr ", "json:attr\n"):
        with pytest.raises(ImportError) as exc_info:
            resolve_variable(path)
        message = str(exc_info.value)
        assert "doesn't look like a variable path" in message, path
        assert "uv add" not in message, path
