import copy
import logging
from unittest.mock import MagicMock

from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core.storage import MemoryStorage
from deerflow.agents.memory.backends.deermem.deermem.core.updater import MemoryUpdater, _extract_text, _normalize_memory_update_data
from deerflow.agents.memory.manager import _host_default_extraction_callback


def _memory(facts: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "version": "1.0",
        "revision": 0,
        "lastUpdated": "",
        "user": {
            "workContext": {"summary": "", "updatedAt": ""},
            "personalContext": {"summary": "", "updatedAt": ""},
            "topOfMind": {"summary": "", "updatedAt": ""},
        },
        "history": {
            "recentMonths": {"summary": "", "updatedAt": ""},
            "earlierContext": {"summary": "", "updatedAt": ""},
            "longTermBackground": {"summary": "", "updatedAt": ""},
        },
        "facts": copy.deepcopy(facts or []),
    }


class _Storage(MemoryStorage):
    def load(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, object]:
        return _memory()

    def reload(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, object]:
        return self.load(agent_name, user_id=user_id)

    def save(
        self,
        memory_data: dict[str, object],
        agent_name: str | None = None,
        *,
        user_id: str | None = None,
        expected_revision: int | None = None,
    ) -> bool:
        return True


def _updater(**config_overrides: object) -> MemoryUpdater:
    config = DeerMemConfig()
    for key, value in config_overrides.items():
        setattr(config, key, value)
    return MemoryUpdater(config, _Storage(), llm=None)


def _fact(content: str, **overrides: object) -> dict[str, object]:
    fact: dict[str, object] = {
        "content": content,
        "category": "preference",
        "confidence": 0.9,
        "scope": "user",
        "durability": "durable",
        "authority": "descriptive",
    }
    fact.update(overrides)
    return fact


def _stored_fact(fact_id: str, content: str) -> dict[str, object]:
    return {
        "id": fact_id,
        "content": content,
        "category": "preference",
        "confidence": 0.9,
        "createdAt": "2026-01-01T00:00:00Z",
        "source": "thread-old",
    }


def test_normalize_preserves_extraction_only_classification_fields() -> None:
    normalized = _normalize_memory_update_data(
        {
            "user": {},
            "history": {},
            "newFacts": [_fact("User prefers concise answers")],
            "factsToRemove": [],
        }
    )

    assert normalized["newFacts"][0]["scope"] == "user"
    assert normalized["newFacts"][0]["durability"] == "durable"
    assert normalized["newFacts"][0]["authority"] == "descriptive"


def test_fact_gate_accepts_only_durable_descriptive_user_facts() -> None:
    updater = _updater(fact_confidence_threshold=0.7)
    metrics: dict[str, object] = {}
    update = {
        "user": {},
        "history": {},
        "factsToRemove": [],
        "newFacts": [
            _fact("accepted"),
            _fact("thread only", scope="thread"),
            _fact("temporary", durability="temporary"),
            _fact("permission", authority="transactional"),
            {"content": "missing labels", "category": "context", "confidence": 0.9},
        ],
    }

    result = updater._apply_updates(_memory(), update, thread_id="thread-new", metrics=metrics)

    assert [fact["content"] for fact in result["facts"]] == ["accepted"]
    assert set(result["facts"][0]) == {"id", "content", "category", "confidence", "createdAt", "source"}
    assert metrics["rejected_by_scope_gate"] == 4
    assert metrics["scope_gate_rejections"] == {
        "facts": {"missing": 1, "scope": 1, "durability": 1, "authority": 1},
        "summaries": {"missing": 0, "scope": 0, "authority": 0},
        "removals": {"missing": 0, "scope": 0, "replacement": 0},
        "consolidations": {"missing": 0, "scope": 0, "durability": 0, "authority": 0},
    }


def test_summary_gate_requires_user_scope_and_descriptive_authority() -> None:
    updater = _updater()
    current = _memory()
    current["user"]["personalContext"]["summary"] = "Existing summary"
    metrics: dict[str, object] = {}
    update = {
        "user": {
            "workContext": {"summary": "User is a software engineer", "shouldUpdate": True, "scope": "user", "authority": "descriptive"},
            "personalContext": {"summary": "Constraint for this PR", "shouldUpdate": True, "scope": "project", "authority": "descriptive"},
            "topOfMind": {"summary": "User granted push access", "shouldUpdate": True, "scope": "user", "authority": "transactional"},
        },
        "history": {
            "recentMonths": {"summary": "Missing authority label", "shouldUpdate": True, "scope": "user"},
        },
        "newFacts": [],
        "factsToRemove": [],
    }

    result = updater._apply_updates(current, update, metrics=metrics)

    assert result["user"]["workContext"]["summary"] == "User is a software engineer"
    assert set(result["user"]["workContext"]) == {"summary", "updatedAt"}
    assert result["user"]["personalContext"]["summary"] == "Existing summary"
    assert result["user"]["topOfMind"]["summary"] == ""
    assert result["history"]["recentMonths"]["summary"] == ""
    assert metrics["scope_gate_rejections"]["summaries"] == {"missing": 1, "scope": 1, "authority": 1}


def test_thread_scoped_removal_cannot_delete_user_fact() -> None:
    updater = _updater()
    current = _memory([_stored_fact("fact_api", "User generally prefers API compatibility")])
    update = {
        "user": {},
        "history": {},
        "newFacts": [],
        "factsToRemove": [{"id": "fact_api", "scope": "thread", "reason": "This PR may break the API"}],
    }

    result = updater._apply_updates(current, update)

    assert [fact["id"] for fact in result["facts"]] == ["fact_api"]


def test_unreasoned_user_scoped_removal_fails_closed() -> None:
    updater = _updater()
    current = _memory([_stored_fact("fact_api", "User generally prefers API compatibility")])
    update = {
        "user": {},
        "history": {},
        "newFacts": [],
        "factsToRemove": [{"id": "fact_api", "scope": "user"}],
    }

    result = updater._apply_updates(current, update)

    assert [fact["id"] for fact in result["facts"]] == ["fact_api"]


def test_paired_removal_is_skipped_when_replacement_fails_scope_gate() -> None:
    updater = _updater(fact_confidence_threshold=0.7)
    current = _memory([_stored_fact("fact_api", "User generally prefers API compatibility")])
    metrics: dict[str, object] = {}
    update = {
        "user": {},
        "history": {},
        "newFacts": [_fact("This PR may break the API", scope="thread", durability="temporary")],
        "factsToRemove": [
            {
                "id": "fact_api",
                "scope": "user",
                "reason": "Preference changed",
                "replacementFactIndex": 0,
            }
        ],
    }

    result = updater._apply_updates(current, update, metrics=metrics)

    assert [fact["id"] for fact in result["facts"]] == ["fact_api"]
    assert metrics["scope_gate_rejections"]["removals"]["replacement"] == 1


def test_paired_removal_is_skipped_when_replacement_fails_confidence_gate() -> None:
    updater = _updater(fact_confidence_threshold=0.7)
    current = _memory([_stored_fact("fact_api", "User generally prefers API compatibility")])
    metrics: dict[str, object] = {}
    update = {
        "user": {},
        "history": {},
        "newFacts": [_fact("User no longer requires API compatibility", confidence=0.69)],
        "factsToRemove": [
            {
                "id": "fact_api",
                "scope": "user",
                "reason": "Preference changed",
                "replacementFactIndex": 0,
            }
        ],
    }

    result = updater._apply_updates(current, update, metrics=metrics)

    assert [fact["id"] for fact in result["facts"]] == ["fact_api"]
    assert metrics["facts_passed_scope_gate"] == 1
    assert metrics["rejected_low_confidence"] == 1
    assert metrics["scope_gate_rejections"]["removals"]["replacement"] == 1


def test_paired_removal_is_atomic_when_replacement_is_persisted() -> None:
    updater = _updater(fact_confidence_threshold=0.7, max_facts=100)
    current = _memory([_stored_fact("fact_editor", "User prefers Vim")])
    update = {
        "user": {},
        "history": {},
        "newFacts": [_fact("User now prefers VS Code")],
        "factsToRemove": [
            {
                "id": "fact_editor",
                "scope": "user",
                "reason": "User changed their durable editor preference",
                "replacementFactIndex": 0,
            }
        ],
    }

    result = updater._apply_updates(current, update)

    assert [fact["content"] for fact in result["facts"]] == ["User now prefers VS Code"]


def test_paired_removal_is_skipped_when_replacement_is_trimmed() -> None:
    updater = _updater(fact_confidence_threshold=0.7, max_facts=1)
    current = _memory([_stored_fact("fact_editor", "User prefers Vim")])
    update = {
        "user": {},
        "history": {},
        "newFacts": [_fact("User now prefers VS Code", confidence=0.8)],
        "factsToRemove": [
            {
                "id": "fact_editor",
                "scope": "user",
                "reason": "User changed their durable editor preference",
                "replacementFactIndex": 0,
            }
        ],
    }

    result = updater._apply_updates(current, update)

    assert [fact["content"] for fact in result["facts"]] == ["User prefers Vim"]


def test_missing_classification_rejects_one_fact_without_aborting_other_updates() -> None:
    updater = _updater(fact_confidence_threshold=0.7, max_facts=100)
    current = _memory([_stored_fact("fact_old", "Old durable preference")])
    normalized = _normalize_memory_update_data(
        {
            "user": {},
            "history": {},
            "newFacts": [
                _fact("Accepted durable preference"),
                {"content": "Unclassified replacement", "category": "preference", "confidence": 0.9},
            ],
            "factsToRemove": [
                {
                    "id": "fact_old",
                    "scope": "user",
                    "reason": "Replace it",
                    "replacementFactIndex": 1,
                }
            ],
        }
    )

    result = updater._apply_updates(current, normalized)

    assert {fact["content"] for fact in result["facts"]} == {
        "Old durable preference",
        "Accepted durable preference",
    }


def test_legacy_string_removal_fails_closed_and_reports_missing_scope() -> None:
    updater = _updater()
    current = _memory([_stored_fact("fact_api", "User generally prefers API compatibility")])
    metrics: dict[str, object] = {}
    normalized = _normalize_memory_update_data(
        {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": ["fact_api"],
        }
    )

    result = updater._apply_updates(current, normalized, metrics=metrics)

    assert normalized["factsToRemove"] == [{"id": "fact_api"}]
    assert [fact["id"] for fact in result["facts"]] == ["fact_api"]
    assert metrics["scope_gate_rejections"]["removals"]["missing"] == 1


def test_signal_hints_require_cross_task_user_scope() -> None:
    updater = _updater()

    hints = updater._build_signal_hints(frozenset({"correction", "goal", "decision"}))

    assert "user-level" in hints
    assert "current task" in hints
    assert "thread" in hints


def test_prompt_requires_scope_labels_for_every_mutating_path() -> None:
    updater = _updater()
    message = MagicMock()
    message.type = "human"
    message.content = "Remember that I prefer concise answers."

    prepared = updater._prepare_update_prompt([message], agent_name="lead-agent", signals=frozenset())

    assert prepared is not None
    _, prompt = prepared
    prompt_text = "\n".join(_extract_text(getattr(item, "content", item)) for item in prompt)
    assert 'scope="user"' in prompt_text
    assert 'durability="durable"' in prompt_text
    assert 'authority="transactional"' in prompt_text
    assert '"scope": "user|thread|project", "authority": "descriptive|transactional"' in prompt_text
    assert "replacementFactIndex" in prompt_text
    assert "unrelated future thread" in prompt_text


def test_unclassified_consolidation_keeps_sources_and_reports_rejection() -> None:
    updater = _updater(
        consolidation_enabled=True,
        consolidation_min_facts=2,
        consolidation_max_groups_per_cycle=1,
        consolidation_max_sources=4,
    )
    current = _memory(
        [
            _stored_fact("fact_a", "User uses Python"),
            _stored_fact("fact_b", "User uses Rust"),
        ]
    )
    metrics: dict[str, object] = {}
    update = {
        "user": {},
        "history": {},
        "newFacts": [],
        "factsToRemove": [],
        "factsToConsolidate": [
            {
                "sourceIds": ["fact_a", "fact_b"],
                "consolidated": {
                    "content": "User uses Python and Rust",
                    "category": "preference",
                    "confidence": 0.9,
                },
            }
        ],
    }

    result = updater._apply_updates(current, update, metrics=metrics)

    assert {fact["id"] for fact in result["facts"]} == {"fact_a", "fact_b"}
    assert metrics["scope_gate_rejections"]["consolidations"]["missing"] == 1


def test_default_observability_warns_when_fact_scope_gate_rejects_most_items(caplog) -> None:
    payload = {
        "thread_id": "thread-scope",
        "model_name": "test-model",
        "success": True,
        "facts_extracted": 2,
        "facts_passed_confidence": 2,
        "rejected_low_confidence": 0,
        "rejected_by_scope_gate": 2,
        "scope_gate_rejections": {
            "facts": {"missing": 2, "scope": 0, "durability": 0, "authority": 0},
            "summaries": {"missing": 0, "scope": 0, "authority": 0},
            "removals": {"missing": 0, "scope": 0, "replacement": 0},
            "consolidations": {"missing": 0, "scope": 0, "durability": 0, "authority": 0},
        },
    }

    with caplog.at_level(logging.WARNING):
        _host_default_extraction_callback(payload)

    assert "scope-gate rejection rate 100% exceeds 60%" in caplog.text
