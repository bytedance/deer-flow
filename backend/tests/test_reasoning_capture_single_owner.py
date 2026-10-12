"""Ownership gate for the reasoning-capture plumbing MiMo and StepFun shared.

``patched_mimo`` and ``patched_stepfun`` each carried a byte-identical copy of
two helpers: attach a reasoning string to a LangChain message without mutating
the message the caller still holds, and read ``choices[index].message`` out of a
response that may be a dict payload, an SDK object, or a chunk with no choices.
Two owners for one rule means a leak fix (or an identity fix) landing in one
provider silently leaves the other behind.

These tests pin three things the extraction must not silently give back:

1. the owner's behaviour, case by case — including the two properties that are
   easy to lose in a refactor: the input message is never mutated, and a copy is
   returned even when the value already matched;
2. that both providers actually call the owner (binding identity, plus the
   streaming path exercised end to end), and the private helpers are gone;
3. a source census over ``models/``: no module may restate either function body,
   and exactly the two migrated providers import the owner.

Providers whose reasoning handling genuinely differs are out of scope and stay
local: ``patched_minimax`` merges streamed deltas, ``patched_deepseek`` and
``vllm_provider`` read different field spellings, and each keeps its own
extraction. ``test_the_census_compares_shapes_not_names`` pins that this gate
does not sweep them in.
"""

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk

import deerflow.models.patched_mimo as patched_mimo
import deerflow.models.patched_minimax as patched_minimax
import deerflow.models.patched_stepfun as patched_stepfun
import deerflow.models.reasoning_capture as owner

MODELS_ROOT = Path(owner.__file__).resolve().parent

PROVIDERS = {
    "patched_mimo": (patched_mimo, patched_mimo.PatchedChatMiMo, "mimo-v2.5-pro"),
    "patched_stepfun": (patched_stepfun, patched_stepfun.PatchedChatStepFun, "step-3.7-flash"),
}
REASONING = "checked the tool output first"


def _functions(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _body_hash(fn: ast.AST) -> str:
    """Hash the executable body, ignoring the docstring a provider may or may not carry."""
    body = list(fn.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) and isinstance(body[0].value.value, str):
        body = body[1:]
    return ast.unparse(ast.Module(body=body, type_ignores=[]))


def _owner_hashes() -> dict[str, str]:
    return {_body_hash(fn): fn.name for fn in _functions(ast.parse(Path(owner.__file__).read_text(encoding="utf-8")))}


# --- 1. the bar -----------------------------------------------------------------


def test_with_reasoning_content_attaches_without_mutating() -> None:
    message = AIMessage(content="answer", additional_kwargs={"other": "kept"})
    patched = owner.with_reasoning_content(message, REASONING)

    assert patched.additional_kwargs["reasoning_content"] == REASONING
    assert patched.additional_kwargs["other"] == "kept"
    assert "reasoning_content" not in message.additional_kwargs, "the caller's message was mutated"
    assert patched is not message


def test_with_reasoning_content_still_returns_a_copy_when_value_matches() -> None:
    message = AIMessage(content="answer", additional_kwargs={"reasoning_content": REASONING})
    patched = owner.with_reasoning_content(message, REASONING)

    assert patched.additional_kwargs["reasoning_content"] == REASONING
    assert patched is not message, "callers replay through model_copy; identity must stay predictable"


def test_with_reasoning_content_overwrites_a_non_string_and_handles_chunks() -> None:
    message = AIMessage(content="answer", additional_kwargs={"reasoning_content": None})
    assert owner.with_reasoning_content(message, REASONING).additional_kwargs["reasoning_content"] == REASONING

    chunk = AIMessageChunk(content="par")
    patched = owner.with_reasoning_content(chunk, REASONING)
    assert isinstance(patched, AIMessageChunk) and patched.additional_kwargs["reasoning_content"] == REASONING


@pytest.mark.parametrize(
    ("response", "index", "expected"),
    [
        (SimpleNamespace(choices=[SimpleNamespace(message="typed")]), 0, "typed"),
        (SimpleNamespace(choices=[SimpleNamespace(message="typed")]), 1, None),
        (SimpleNamespace(choices=None), 0, None),
        ({"choices": [{"message": "payload shaped"}]}, 0, None),
        (SimpleNamespace(choices=[SimpleNamespace()]), 0, None),
        (SimpleNamespace(choices=7), 0, None),
    ],
)
def test_typed_choice_message_reports_absence_rather_than_raising(response, index: int, expected) -> None:
    assert owner.typed_choice_message(response, index) is expected


# --- 2. both providers really go through the owner ----------------------------


@pytest.mark.parametrize(("module", "cls", "model_name"), sorted(PROVIDERS.values(), key=lambda x: x[0].__name__))
def test_provider_names_are_the_owner_not_a_restatement(module, cls, model_name: str) -> None:
    assert module.with_reasoning_content is owner.with_reasoning_content
    assert module.typed_choice_message is owner.typed_choice_message
    for stale in ("_with_reasoning_content", "_get_typed_choice_message"):
        assert not hasattr(module, stale), f"{module.__name__} still carries its private {stale}"


@pytest.mark.parametrize(("module", "cls", "model_name"), sorted(PROVIDERS.values(), key=lambda x: x[0].__name__))
def test_streaming_path_still_captures_reasoning_through_the_owner(module, cls, model_name: str) -> None:
    """Behaviour at a real call site, not just an identity check."""
    model = cls(model=model_name, api_key="test-key", base_url="https://example.invalid/v1")
    chunk = model._convert_chunk_to_generation_chunk(
        {"choices": [{"delta": {"role": "assistant", "reasoning_content": REASONING}}]},
        AIMessageChunk,
        {},
    )
    assert chunk is not None
    assert chunk.message.additional_kwargs["reasoning_content"] == REASONING


# --- 3. census over models/ ---------------------------------------------------


def test_no_model_module_restates_an_owned_body() -> None:
    hashes = _owner_hashes()
    offenders = []
    for path in sorted(MODELS_ROOT.glob("*.py")):
        if path.name == "reasoning_capture.py":
            continue
        for fn in _functions(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
            if _body_hash(fn) in hashes:
                offenders.append(f"{path.name}::{fn.name}")
    assert offenders == [], f"shared reasoning bodies belong to the owner: found in {offenders}"


def test_the_census_compares_shapes_not_names() -> None:
    """MiMo/StepFun's near-neighbour keeps its own merge logic and must stay untouched."""
    minimax = next(fn for fn in _functions(ast.parse(Path(patched_minimax.__file__).read_text(encoding="utf-8"))) if fn.name == "_with_reasoning_content")
    assert _body_hash(minimax) not in _owner_hashes(), "the census would be claiming a fold that never happened"


def test_exactly_the_migrated_providers_import_the_owner() -> None:
    importers = {path.name for path in sorted(MODELS_ROOT.glob("*.py")) if path.name != "reasoning_capture.py" and "from deerflow.models.reasoning_capture import" in path.read_text(encoding="utf-8")}
    assert importers == {"patched_mimo.py", "patched_stepfun.py"}
