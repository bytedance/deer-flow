"""Ownership gate for resolving a memory judging side's provider class path.

``prescreen/contract.py`` and ``signals/contract.py`` each carried a
byte-identical copy of the resolver their two ``resolve_*`` faces wrap: reject an
unknown mode, require ``use`` for a live mode, resolve the class path, insist the
target is instantiable, construct with ``mode`` plus the config -- and fail loudly
instead of silently degrading to "no provider". Two owners for one rule means a
fix to the fail-loudly rule lands on one side of the judging pair and not the
other, with nothing failing to say so.

These tests pin three things the extraction must not silently give back:

1. the owner's behaviour, value by value, including the exact error text that
   ``tests/test_memory_prescreen.py`` and operator-facing config validation
   already assert on;
2. that both contract faces still route through the owner at runtime --
   retargeting the owner changes both sides, which a private copy would not --
   while each side keeps its own mode vocabulary and its own configuration
   source in the message;
3. a source census over ``agents/memory/``: no module except the owner may restate
   the resolution mechanics. It is a source-pattern gate over this subtree, not a
   repo-wide proof about arbitrary provider construction.

Deliberately not owned here: which spellings each side accepts (``off`` /
``shadow`` / ``enforce`` for the pre-screen, ``off`` / ``shadow`` / ``hints`` for
the classifier) and what a judging failure means for the batch. Those are adapter
policy and are passed in as ``modes`` and ``off_mode``.
"""

import ast
import inspect
from pathlib import Path

import pytest

from deerflow.agents.memory import judging
from deerflow.agents.memory.prescreen import contract as prescreen_contract
from deerflow.agents.memory.prescreen.contract import resolve_memory_prescreen
from deerflow.agents.memory.signals import contract as signals_contract
from deerflow.agents.memory.signals.contract import resolve_memory_signal_classifier

MEMORY_ROOT = Path(inspect.getfile(judging)).resolve().parent

_API_KEY = "memory-judging-owner-test-key"
_PRESCREEN = "deerflow.agents.memory.prescreen.typesafe:TypeSafeMemoryPrescreen"
_CLASSIFIER = "deerflow.agents.memory.signals.typesafe:TypeSafeSignalClassifier"

# A module attribute that exists but is not callable: the "is not instantiable"
# branch has to be distinguishable from the "could not be resolved" one.
_NOT_A_CLASS = "deerflow.agents.memory.judging:_DIGEST_CHARS"

SIDES = {
    "prescreen": {
        "face": resolve_memory_prescreen,
        "contract": prescreen_contract,
        "use": _PRESCREEN,
        "live_mode": "enforce",
        "source": "memory.prescreen.config",
        "protocol": prescreen_contract.MemoryPrescreenProvider,
    },
    "signal_classification": {
        "face": resolve_memory_signal_classifier,
        "contract": signals_contract,
        "use": _CLASSIFIER,
        "live_mode": "hints",
        "source": "memory.signal_classification.config",
        "protocol": signals_contract.MemorySignalProvider,
    },
}


@pytest.fixture(params=sorted(SIDES), ids=sorted(SIDES))
def side(request):
    """One judging side's key, so every rule is checked against both faces."""
    return request.param


# --- 1. the bar, value by value -------------------------------------------


def test_off_mode_resolves_nothing_and_touches_no_class_path(side, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    entry = SIDES[side]

    # An unusable class path must not matter while the side is off: 'off'
    # resolves nothing, constructs nothing and validates no credentials.
    assert entry["face"](mode=entry["contract"].MODE_OFF, use="not.a.real.module:Cls") is None


def test_unknown_mode_lists_that_side_only(side):
    entry = SIDES[side]
    modes = entry["contract"].MODES

    with pytest.raises(ValueError) as excinfo:
        entry["face"](mode="sometimes", use=entry["use"])

    message = str(excinfo.value)
    assert message == f"{entry['source']} mode must be one of {list(modes)}, got 'sometimes'"


def test_live_mode_without_a_class_path_fails_loudly(side):
    entry = SIDES[side]

    with pytest.raises(ValueError, match=r"needs 'use' when mode='"):
        entry["face"](mode=entry["live_mode"], use=None)
    with pytest.raises(ValueError, match=r"needs 'use' when mode='"):
        entry["face"](mode=entry["live_mode"], use="")


def test_unusable_class_path_names_the_source_and_the_path(side):
    entry = SIDES[side]

    with pytest.raises(ValueError, match="could not be resolved") as excinfo:
        entry["face"](mode=entry["live_mode"], use="not.a.real.module:Cls")

    assert entry["source"] in str(excinfo.value)
    assert "not.a.real.module:Cls" in str(excinfo.value)


def test_resolved_but_not_instantiable_is_a_distinct_failure(side):
    entry = SIDES[side]

    with pytest.raises(ValueError, match="is not instantiable") as excinfo:
        entry["face"](mode=entry["live_mode"], use=_NOT_A_CLASS)

    assert "could not be resolved" not in str(excinfo.value)


def test_live_mode_constructs_with_mode_and_config(side, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    entry = SIDES[side]

    provider = entry["face"](mode=entry["live_mode"], use=entry["use"], config={"api_key": _API_KEY})

    # Each provider constructor validates its own mode spelling and refuses one
    # outside its modes, so reaching a constructed provider here is the proof
    # that the live mode was forwarded rather than dropped or defaulted.
    assert not isinstance(provider, type), "the owner must hand back a constructed provider, not the class"
    assert isinstance(provider, entry["protocol"]), "a live mode must construct the resolved class against the side's contract"


def test_the_owner_asks_its_caller_which_mode_means_off():
    """``off_mode`` is load-bearing: the owner must not decide the off spelling.

    A bespoke vocabulary whose off mode is not ``"off"`` has to resolve to
    ``None`` with an unusable class path, which only holds if the owner compares
    against the caller's ``off_mode`` rather than a literal it picked itself.
    """
    assert (
        judging.resolve_judging_provider(
            mode="quiet",
            use="not.a.real.module:Cls",
            config=None,
            configuration_source="memory.example.config",
            modes=("quiet", "live"),
            off_mode="quiet",
        )
        is None
    )

    with pytest.raises(ValueError, match=r"mode must be one of \['quiet', 'live'\]") as excinfo:
        judging.resolve_judging_provider(
            mode="off",
            use=_PRESCREEN,
            config=None,
            configuration_source="memory.example.config",
            modes=("quiet", "live"),
            off_mode="quiet",
        )

    assert "memory.example.config" in str(excinfo.value), "the caller's source label must reach the message"


def test_empty_config_still_constructs(side, monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", _API_KEY)
    entry = SIDES[side]

    assert entry["face"](mode=entry["live_mode"], use=entry["use"]) is not None
    assert entry["face"](mode=entry["live_mode"], use=entry["use"], config=None) is not None


# --- 2. both faces route through the one owner ------------------------------


def test_both_faces_delegate_to_the_owner_at_runtime(monkeypatch):
    captured: list[dict] = []
    sentinel = object()

    def fake_owner(**kwargs):
        captured.append(kwargs)
        return sentinel

    monkeypatch.setattr(judging, "resolve_judging_provider", fake_owner)

    assert resolve_memory_prescreen(mode="shadow", use=_PRESCREEN) is sentinel
    assert resolve_memory_signal_classifier(mode="shadow", use=_CLASSIFIER) is sentinel

    assert len(captured) == 2, "both contract faces must reach the owner, not a private copy"


def test_each_side_passes_its_own_vocabulary_to_the_owner(monkeypatch):
    captured: list[dict] = []

    def fake_owner(**kwargs):
        captured.append(kwargs)
        return None

    monkeypatch.setattr(judging, "resolve_judging_provider", fake_owner)

    resolve_memory_prescreen(mode="shadow", use=_PRESCREEN)
    resolve_memory_signal_classifier(mode="hints", use=_CLASSIFIER)

    prescreen_call, classifier_call = captured
    assert prescreen_call["modes"] == prescreen_contract.MODES
    assert prescreen_call["off_mode"] == prescreen_contract.MODE_OFF
    assert prescreen_call["configuration_source"] == prescreen_contract.CONFIGURATION_SOURCE
    assert prescreen_call["mode"] == "shadow"
    assert prescreen_call["use"] == _PRESCREEN

    assert classifier_call["modes"] == signals_contract.MODES
    assert classifier_call["off_mode"] == signals_contract.MODE_OFF
    assert classifier_call["configuration_source"] == signals_contract.CONFIGURATION_SOURCE

    assert prescreen_call["modes"] != classifier_call["modes"], "the sides are expected to differ here; the shared owner must not paper that over"


def test_a_public_reexport_of_each_face_still_works(side):
    """The faces are re-exported by their package ``__all__``; the delegation keeps that."""
    entry = SIDES[side]
    package_name = entry["contract"].__name__.rsplit(".contract", maxsplit=1)[0]
    package = __import__(package_name, fromlist=["*"])

    face_name = entry["face"].__name__
    assert face_name in package.__all__
    assert getattr(package, face_name) is entry["face"]


# --- 3. source census -------------------------------------------------------


def _top_level_functions(path: Path) -> dict[str, ast.FunctionDef]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}


def _delegates_to(fn: ast.FunctionDef, owner: str) -> bool:
    """True when everything the function does is one ``return owner(...)`` call."""
    body = list(fn.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        body.pop(0)  # a docstring is not part of the mechanics

    return len(body) == 1 and isinstance(body[0], ast.Return) and isinstance(body[0].value, ast.Call) and getattr(body[0].value.func, "attr", None) == owner


def test_both_contract_faces_are_single_delegations():
    for contract in (prescreen_contract, signals_contract):
        functions = _top_level_functions(Path(contract.__file__))
        face = next(node for name, node in functions.items() if name.startswith("resolve_"))

        assert _delegates_to(face, "resolve_judging_provider"), f"{contract.__name__}::{face.name} grew a body again"


@pytest.mark.parametrize(
    "needle",
    [
        "is not instantiable",
        "could not be resolved",
        "needs 'use' when mode=",
    ],
)
def test_no_module_under_memory_restates_the_shared_mechanics(needle) -> None:
    """The class-path resolution mechanics exist once.

    ``"mode must be one of"`` is deliberately not on this list: each side's
    provider constructor validates its own mode spelling, which is adapter
    policy the shared owner does not take over.
    """
    offenders = [str(path.relative_to(MEMORY_ROOT)) for path in sorted(MEMORY_ROOT.rglob("*.py")) if path.name != "judging.py" and not path.name.startswith("test_") and needle in path.read_text(encoding="utf-8")]

    assert offenders == [], f"{offenders} restate resolution mechanics owned by judging.py"


def test_owner_holds_each_rule_exactly_once() -> None:
    source = Path(inspect.getfile(judging)).read_text(encoding="utf-8")
    functions = _top_level_functions(Path(inspect.getfile(judging)))

    assert list(functions).count("resolve_judging_provider") == 1
    for needle in ("is not instantiable", "could not be resolved", "needs 'use' when mode=", "mode must be one of"):
        assert source.count(needle) == 1, needle
