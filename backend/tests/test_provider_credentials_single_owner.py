"""Ownership gate for the credential rules the bundled retrieval providers share.

``community/lightrag`` and ``community/ragflow`` each carried a byte-identical
copy of three rules: unwrapping and normalizing a configured API key, scrubbing
that key out of text before it reaches a log line or a tool error, and refusing
a configured base URL that smuggles credentials in userinfo. Two owners for one
rule means a hardening fix landing in one provider can leave the other one
leaking, with nothing failing to say so.

These tests pin three things the extraction must not silently give back:

1. the owner's behaviour, value by value (the bar), including the exact marker
   and error text that provider tests and operator log patterns already depend
   on;
2. that every provider face still routes through the owner at runtime —
   retargeting the owner's marker changes all of them, which a private copy
   would not — while each provider keeps its own wording and its own policy on a
   missing key (LightRAG accepts one, RAGFlow refuses it);
3. a source census over ``community/``: no provider package may restate the
   marker, the userinfo rejection, or the ``SecretStr`` unwrap. It is a
   source-pattern gate over provider code, not a repo-wide proof about
   arbitrary credential code. Two neighbours are out of scope on purpose:
   ``community/serper/tools.py::_matches_domain_scope`` also inspects URL
   userinfo, but it is source selection that declines a match, not a
   configuration rule that refuses to load; and model-layer ``get_secret_value``
   readers (``config/managed_models.py``, ``models/claude_provider.py``) unwrap
   for other reasons.
"""

import ast
from pathlib import Path
from typing import Any

import pytest
from pydantic import AnyHttpUrl, SecretStr, TypeAdapter, ValidationError

import deerflow.community.lightrag.client as lightrag_client
import deerflow.community.lightrag.tools as lightrag_tools
import deerflow.community.provider_credentials as owner
import deerflow.community.ragflow.client as ragflow_client
import deerflow.community.ragflow.tools as ragflow_tools

COMMUNITY_ROOT = Path(lightrag_tools.__file__).resolve().parent.parent
PROVIDER_KEY = "sekret-key-42"

PROVIDER_FACES = {
    "lightrag": {
        "tools": lightrag_tools,
        "client_module": lightrag_client,
        "client": lightrag_client.LightRAGClient,
        "api_error": lightrag_client.LightRAGAPIError,
        "settings": lightrag_tools._LightRAGRetrievalSettings,
    },
    "ragflow": {
        "tools": ragflow_tools,
        "client_module": ragflow_client,
        "client": ragflow_client.RAGFlowClient,
        "api_error": ragflow_client.RAGFlowAPIError,
        "settings": ragflow_tools._RAGFlowRetrievalSettings,
    },
}


def _code_nodes(tree: ast.AST):
    """Walk executable syntax, excluding module/class/function docstrings."""
    yield tree
    docstring = None
    if isinstance(tree, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and ast.get_docstring(tree) is not None:
        docstring = tree.body[0]
    for child in ast.iter_child_nodes(tree):
        if child is not docstring:
            yield from _code_nodes(child)


def _functions(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [node for node in _code_nodes(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _settings(provider: str, **values: Any):
    return PROVIDER_FACES[provider]["settings"](**values)


def _single_delegation(fn: ast.AST, owner_name: str) -> bool:
    """The helper is exactly ``return <owner_name>(...)`` — no restated rule."""
    return isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and len(fn.body) == 1 and isinstance(fn.body[0], ast.Return) and getattr(fn.body[0].value.func, "id", None) == owner_name


# --- 1. the bar -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (SecretStr(PROVIDER_KEY), PROVIDER_KEY),
        (SecretStr(f"  {PROVIDER_KEY}  "), PROVIDER_KEY),
        (PROVIDER_KEY, PROVIDER_KEY),
        ("  key  ", "key"),
        ("", None),
        ("   ", None),
        (None, None),
    ],
)
def test_resolve_api_key_normalizes_without_rejecting(raw: Any, expected: str | None) -> None:
    assert owner.resolve_api_key(raw) == expected


@pytest.mark.parametrize(
    ("value", "secret", "expected"),
    [
        (f"a {PROVIDER_KEY} b {PROVIDER_KEY} c", PROVIDER_KEY, f"a {owner.REDACTION_MARKER} b {owner.REDACTION_MARKER} c"),
        (f"http://x?k={PROVIDER_KEY}", PROVIDER_KEY, f"http://x?k={owner.REDACTION_MARKER}"),
        ("nothing to hide", PROVIDER_KEY, "nothing to hide"),
        ("key passed as None", None, "key passed as None"),
    ],
)
def test_redact_secret_replaces_every_occurrence(value: str, secret: str | None, expected: str) -> None:
    assert owner.redact_secret(value, secret) == expected


def test_redact_secret_stringifies_non_strings() -> None:
    assert owner.redact_secret(ValueError(f"boom {PROVIDER_KEY}"), PROVIDER_KEY) == f"boom {owner.REDACTION_MARKER}"


def test_marker_and_message_are_the_contract_strings() -> None:
    assert owner.REDACTION_MARKER == "[REDACTED]"
    assert owner.URL_USERINFO_ERROR == "base_url must not contain username or password information"


def test_reject_url_userinfo_accepts_clean_url_and_refers_credentials() -> None:
    clean = TypeAdapter(AnyHttpUrl).validate_python("http://provider.example:9621")
    assert owner.reject_url_userinfo(clean) is clean
    dirty = TypeAdapter(AnyHttpUrl).validate_python("http://user:email@example.com")
    with pytest.raises(ValueError, match="username or password"):
        owner.reject_url_userinfo(dirty)


# --- 2. every provider face still goes through the owner -----------------------


@pytest.mark.parametrize("provider", sorted(PROVIDER_FACES))
def test_tool_error_redaction_follows_the_owner_marker(provider: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """A private copy would not move when the owner's marker does."""
    faces = PROVIDER_FACES[provider]
    tools, settings_cls = faces["tools"], faces["settings"]
    monkeypatch.setattr(owner, "REDACTION_MARKER", "@@SENTINEL@@")

    settings = settings_cls(api_key=SecretStr(PROVIDER_KEY), base_url="http://provider.example:9621/")
    detail = tools._tool_error(faces["api_error"](f"upstream said {PROVIDER_KEY}"), settings)
    assert "@@SENTINEL@@" in detail and PROVIDER_KEY not in detail

    client = faces["client"](base_url="http://provider.example:9621", api_key=PROVIDER_KEY, timeout=1)
    assert client._redact(f"leaked {PROVIDER_KEY}") == "leaked @@SENTINEL@@"
    assert tools._api_key(settings) == PROVIDER_KEY


@pytest.mark.parametrize("provider", sorted(PROVIDER_FACES))
def test_folded_providers_reduced_their_adapters_to_delegation(provider: str) -> None:
    """Each remaining local helper is one Return calling the owner, nothing restated."""
    faces = PROVIDER_FACES[provider]
    tools_tree = ast.parse(Path(faces["tools"].__file__).read_text(encoding="utf-8"), filename=faces["tools"].__file__)
    client_tree = ast.parse(Path(faces["client_module"].__file__).read_text(encoding="utf-8"), filename=faces["client_module"].__file__)

    for name, owner_name in (("_api_key", "resolve_api_key"), ("_reject_url_userinfo", "reject_url_userinfo")):
        fn = next((node for node in _functions(tools_tree) if node.name == name), None)
        assert fn is not None, f"{provider} lost its {name} adapter"
        assert _single_delegation(fn, owner_name), f"{provider}.{name} must stay a single delegation to {owner_name}"
    redact = next(node for node in _functions(client_tree) if node.name == "_redact")
    assert _single_delegation(redact, "redact_secret"), f"{provider}.client._redact must stay a single delegation"

    assert not hasattr(faces["tools"], "_redact_api_key"), f"{provider} grew a private redaction copy again"


def test_lightrag_still_accepts_an_unconfigured_key() -> None:
    """LightRAG may run without authentication: no key is valid settings, not an error."""
    settings = _settings("lightrag")
    assert lightrag_tools._api_key(settings) is None
    client = lightrag_tools._build_client(settings)
    assert client._api_key is None


def test_ragflow_still_refuses_an_unconfigured_key() -> None:
    """RAGFlow requires a key: the same absent value is a refusal, and the wording is its own."""
    config = type("Cfg", (), {"get_tool_config": lambda _self, _name: type("T", (), {"model_extra": {}})()})()
    settings, error = ragflow_tools._settings_or_error(config)
    assert settings is None and "RAGFlow API key is not configured" in error


def test_ragflow_keeps_dataset_masking_layered_over_credential_redaction() -> None:
    """UUID masking stays provider-local, error-path-only, and rides on the owner."""
    opaque = "0f9e8d7c-6b5a-4321-8fed-cba987654321"
    redacted = ragflow_tools._redact_error(f"scope {opaque} key {PROVIDER_KEY}", PROVIDER_KEY)
    assert "[DATASET_ID]" in redacted and PROVIDER_KEY not in redacted


# --- 3. census: nobody restates the three rules --------------------------------


def _provider_files() -> list[Path]:
    return sorted(p for p in COMMUNITY_ROOT.rglob("*.py") if p.name != "provider_credentials.py")


@pytest.mark.parametrize(
    ("needle", "why"),
    [
        ('"[REDACTED]"', "the redaction marker belongs to the owner"),
        ("get_secret_value()", "the SecretStr unwrap belongs to the owner"),
        ('"base_url must not contain username or password information"', "the validation message belongs to the owner"),
    ],
)
def test_no_provider_package_restates_a_shared_rule(needle: str, why: str) -> None:
    offenders = [str(p.relative_to(COMMUNITY_ROOT)) for p in _provider_files() if needle in p.read_text(encoding="utf-8")]
    assert offenders == [], f"{why}: found in {offenders}"


def _userinfo_refusers(tree: ast.Module) -> list[str]:
    """Functions that inspect URL userinfo *and raise* — the validator's shape."""
    offenders = []
    for fn in _functions(tree):
        tests, raises = [], []
        for node in _code_nodes(fn):
            if isinstance(node, ast.If):
                tests.append(node)
            elif isinstance(node, ast.Raise):
                raises.append(node)
        reads_userinfo = any(any(isinstance(inner, ast.Attribute) and inner.attr in {"username", "password"} for inner in _code_nodes(test)) for test in tests)
        if reads_userinfo and raises:
            offenders.append(fn.name)
    return offenders


def test_no_provider_package_grows_a_second_userinfo_validator() -> None:
    offenders = []
    for path in _provider_files():
        found = _userinfo_refusers(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        offenders.extend(f"{path.relative_to(COMMUNITY_ROOT)}::{name}" for name in found)
    assert offenders == [], f"userinfo rejection belongs to the owner: found in {offenders}"


def test_owner_holds_each_rule_exactly_once() -> None:
    src = (COMMUNITY_ROOT / "provider_credentials.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    assert src.count('"[REDACTED]"') == 1
    assert src.count("get_secret_value()") == 1
    assert sum(1 for node in _code_nodes(tree) if isinstance(node, ast.Attribute) and node.attr == "password") == 1
    assert {f.name for f in _functions(tree)} == {"resolve_api_key", "redact_secret", "reject_url_userinfo"}


def test_settings_models_reject_userinfo_through_the_shared_validator() -> None:
    """Both providers' validation still fires, and reports the owner's text."""
    for provider in sorted(PROVIDER_FACES):
        with pytest.raises(ValidationError) as excinfo:
            _settings(provider, base_url="http://user:email@example.com")
        assert owner.URL_USERINFO_ERROR in str(excinfo.value)
