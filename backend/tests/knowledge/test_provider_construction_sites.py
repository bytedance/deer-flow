"""Guard: provider implementations are built by their factory, never constructed directly.

Spec 2026-09-14: each leg of the provider dimension has exactly one construction point, so
the object a call site gets is always the one the configuration describes.

- **rerank** (§4.1 / P1): the search paths and the recall test must build the *same*
  reranker — an evaluation that grades a different retriever than the one serving queries
  is not an evaluation. The failure is silent, too: the wrong provider usually raises, and
  ``RerankerError`` degrades to the embedding-cosine order, so nothing surfaces.
- **embedding** (§4.2 / P3): the same rule, with a wider blast radius — a direct
  construction would ignore the configured provider *and* the sparse route, so a document
  indexed through it lands in a different vector space than the query side.
- **parse** (§4.4 / P2): one resolution point, ``parse_document``.

Scope, the other way: this covers *construction by class name*. An aliased import
(``DashScopeReranker as DS``), a ``getattr`` lookup, or a subclass would slip past — the
guard's job is to block the shape a regression actually takes (copying the line above it),
not to be a proof.
"""

from __future__ import annotations

import ast
from pathlib import Path

from deerflow_knowledge.providers import PROVIDER_ALLOWLIST

_BACKEND = Path(__file__).resolve().parents[2]
_PRODUCTION_ROOTS = (
    _BACKEND / "app",
    _BACKEND / "packages" / "harness" / "deerflow",
)
#: Legs whose implementations must be built through their factory. ``sparse`` is absent on
#: purpose: its local BM25 encoder is not an allowlist implementation and is constructed
#: inside ``embedder_factory`` itself.
_GUARDED_LEGS = ("embedding", "rerank", "parse")
#: Class names of every allowlisted implementation of those legs — driven by the table, so a
#: new provider extends the guard instead of escaping it.
_GUARDED_CLASSES = {spec.implementation.rsplit(":", 1)[-1] for leg in _GUARDED_LEGS for spec in PROVIDER_ALLOWLIST[leg].values()}


def _called_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def test_no_production_module_constructs_a_provider_directly():
    offenders: list[str] = []
    for root in _PRODUCTION_ROOTS:
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = _called_name(node)
                if name in _GUARDED_CLASSES:
                    offenders.append(f"{path.relative_to(_BACKEND)}:{node.lineno} -> {name}()")

    assert not offenders, "provider 实现只能经 build_embedder() / build_reranker() / build_parse_provider() 构造，直连构造点：" + "; ".join(offenders)
