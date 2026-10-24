"""Tests for non-finite and out-of-range numbers in memory update responses.

A model can answer with a JSON number outside float range (``1e400`` parses to
``inf``) or with ``NaN``, and an unbounded integer such as ``10**400`` raises
``OverflowError`` in ``float()``. These optional fields are dropped or defaulted
per entry, as ``_normalize_memory_update_fact`` already does, instead of failing
the whole batch and losing the valid facts in the same response.
"""

import json

from deerflow.agents.memory.backends.deermem.deermem.core.updater import _parse_memory_update_response

_VALID_FACT = {
    "content": "User prefers dark mode",
    "category": "preference",
    "confidence": 0.9,
    "scope": "user",
    "durability": "durable",
    "authority": "descriptive",
}


def _response(extra):
    return '{"user":{},"history":{},"newFacts":[' + json.dumps(_VALID_FACT) + "]," + extra + "}"


def test_infinite_extend_by_days_is_dropped():
    # 1e400 is outside float range, so json parses it to inf and int(inf) raises.
    parsed = _parse_memory_update_response(_response('"staleFactsToExtend":[{"id":"fact_1","extend_by_days":1e400}]'))

    assert len(parsed["newFacts"]) == 1
    assert parsed["staleFactsToExtend"] == []


def test_nan_extend_by_days_is_dropped():
    parsed = _parse_memory_update_response(_response('"staleFactsToExtend":[{"id":"fact_1","extend_by_days":NaN}]'))

    assert len(parsed["newFacts"]) == 1
    assert parsed["staleFactsToExtend"] == []


def test_unbounded_integer_consolidation_confidence_defaults():
    # float(10**400) raises OverflowError; the entry keeps its default confidence.
    parsed = _parse_memory_update_response(_response('"factsToConsolidate":[{"sourceIds":["fact_a","fact_b"],"consolidated":{"content":"Merged fact","category":"knowledge","confidence":' + "1" + "0" * 400 + "}}]"))

    assert len(parsed["newFacts"]) == 1
    assert parsed["factsToConsolidate"][0]["consolidated"]["confidence"] == 0.9


def test_finite_values_are_kept():
    parsed = _parse_memory_update_response(
        _response('"staleFactsToExtend":[{"id":"fact_1","extend_by_days":30}],"factsToConsolidate":[{"sourceIds":["fact_a","fact_b"],"consolidated":{"content":"Merged fact","category":"knowledge","confidence":0.7}}]')
    )

    assert parsed["staleFactsToExtend"][0]["extend_by_days"] == 30
    assert parsed["factsToConsolidate"][0]["consolidated"]["confidence"] == 0.7
