"""An unbounded stored fact confidence must not abort memory reads or imports.

A memory document is editable JSON, so ``confidence`` can be an arbitrary
precision integer such as ``10**400``. ``float()`` raises ``OverflowError`` on
it; every fact-confidence coercion on a read or import path must treat that
like any other unusable value instead of failing the whole operation.
"""

from deerflow.agents.memory.backends.deermem.deermem.core.prompt import _coerce_confidence as prompt_confidence
from deerflow.agents.memory.backends.deermem.deermem.core.relevance import _coerce_confidence as relevance_confidence
from deerflow.agents.memory.backends.deermem.deermem.core.storage import normalize_memory_data

UNBOUNDED = 10**400


def test_legacy_import_normalization_falls_back_to_the_default_confidence():
    normalized = normalize_memory_data({"facts": [{"content": "User likes Rust", "confidence": UNBOUNDED}]})

    assert normalized["facts"][0]["confidence"] == 0.5


def test_prompt_confidence_falls_back_to_the_caller_default():
    assert prompt_confidence(UNBOUNDED, default=0.0) == 0.0


def test_relevance_confidence_falls_back_to_zero():
    assert relevance_confidence({"confidence": UNBOUNDED}) == 0.0
