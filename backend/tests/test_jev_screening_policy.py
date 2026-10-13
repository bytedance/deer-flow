"""Screening policy identity through the host's assembly descriptor.

The middleware reaches the descriptor the way a ``plugins:`` entry does: loaded
by the extension loader and wrapped by host isolation, which the descriptor
unwraps to read the extension's own policy declaration.
"""

import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest
from deerflow_extension_api import AgentBuildContext, AgentScope, Placement

from deerflow.agents.assembly_descriptor import build_assembly_descriptor
from deerflow.extensions.anchors import outermost
from deerflow.extensions.injection import inject_middlewares
from deerflow.extensions.loader import ExtensionSpec, load_extensions

EXAMPLE = Path(__file__).resolve().parents[2] / "examples/deerflow-extension-jev-screening"


@pytest.fixture(autouse=True)
def example_path(monkeypatch):
    monkeypatch.syspath_prepend(str(EXAMPLE))


def contributed(**options):
    extensions, diagnostics = load_extensions([ExtensionSpec(use="deerflow_extension_jev_screening:install", config={"enabled": True, **options})])
    assert [d for d in diagnostics if d.level == "error"] == []
    stack, _provenance, construction = inject_middlewares([], {Placement.TOOL_VISIBLE: outermost()}, AgentScope.LEAD, AgentBuildContext(scope=AgentScope.LEAD), extensions)
    assert construction == []
    return stack


def assembly(**options):
    return build_assembly_descriptor(
        namespace="screening-policy-test",
        agent_name="test",
        requested_model="fixed-model",
        effective_model="fixed-model",
        model_config=SimpleNamespace(model="fixed-model"),
        thinking_enabled=False,
        reasoning_effort=None,
        rendered_base_prompt="Fixed synthetic base prompt.",
        tools=[],
        middlewares=contributed(**options),
        deferred_names=frozenset(),
        enabled_skills=[],
        effective_policies={},
    )


@pytest.mark.parametrize(
    "options",
    [
        {"enabled": False},
        {"endpoint": "https://other.example.test/private-endpoint"},
        {"model": "another-model"},
        {"threshold": 0.7},
        {"max_excerpt_chars": 2000},
        {"timeout_seconds": 1.0},
        {"api_key_env": "ALTERNATE_SCREENING_KEY"},
    ],
)
def test_each_screening_option_changes_the_real_assembly_fingerprint(options):
    assert assembly(**options).fingerprint != assembly().fingerprint


@pytest.mark.parametrize("field", ["_INSTRUCTION", "_CRITERIA", "_MARKER"])
def test_screening_text_changes_move_the_assembly_fingerprint(monkeypatch, field):
    from deerflow_extension_jev_screening import screener

    before = assembly().fingerprint
    original = getattr(screener, field)
    changed = {**original, "true": "Synthetic changed criterion."} if isinstance(original, dict) else original + " Synthetic changed text."
    monkeypatch.setattr(screener, field, changed)
    assert assembly().fingerprint != before


def test_policy_is_stable_json_safe_and_does_not_expose_endpoint_prompt_or_keys(monkeypatch):
    from deerflow_extension_jev_screening import screener

    endpoint = "https://private.example.test/tenant-canary"
    instruction = "Synthetic private screening question canary."
    criteria = {"true": "Synthetic private positive canary.", "false": "Synthetic private negative canary."}
    marker = "Synthetic private marker canary."
    monkeypatch.setenv("TYPESAFE_API_KEY", "secret-value-canary-A")
    monkeypatch.setattr(screener, "_INSTRUCTION", instruction)
    monkeypatch.setattr(screener, "_CRITERIA", criteria)
    monkeypatch.setattr(screener, "_MARKER", marker)
    first = assembly(endpoint=endpoint)
    (entry,) = first.middlewares
    assert entry.extension, "the descriptor must attribute the middleware to its extension"
    declared = entry.policy_parameters
    assert "probed" not in declared
    assert declared["enabled"] is True
    assert declared["api_key_env"] == "TYPESAFE_API_KEY"
    assert declared["max_screened_messages"] == 8
    for name in ("endpoint_sha256", "question_sha256", "marker_sha256"):
        assert len(declared[name]) == 64 and all(c in "0123456789abcdef" for c in declared[name])
    serialized = json.dumps(asdict(first), sort_keys=True, allow_nan=False)
    for private in (endpoint, instruction, marker, *criteria.values(), "secret-value-canary-A"):
        assert private not in serialized
    assert "endpoint" not in declared
    assert assembly(endpoint=endpoint).fingerprint == first.fingerprint
    monkeypatch.setenv("TYPESAFE_API_KEY", "secret-value-canary-B")
    rotated = assembly(endpoint=endpoint)
    assert rotated.fingerprint == first.fingerprint
    assert "secret-value-canary-B" not in json.dumps(asdict(rotated))
    monkeypatch.delenv("TYPESAFE_API_KEY")
    assert assembly(endpoint=endpoint).fingerprint == first.fingerprint
    monkeypatch.setattr(screener, "_CRITERIA", dict(reversed(list(criteria.items()))))
    assert assembly(endpoint=endpoint).fingerprint == first.fingerprint
