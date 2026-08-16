"""Tests for pre-runtime standalone Studio provenance repair."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from uuid import NAMESPACE_DNS, uuid4, uuid5

from app.gateway.langgraph_studio import (
    configured_system_assistant_ids,
    repair_local_dev_persistence_before_runtime,
    repair_persisted_assistant_provenance,
)


def test_configured_system_assistant_ids_are_deterministic():
    namespace = uuid4()
    graphs = json.dumps(
        {
            "alpha": "./graph.py:alpha",
            "beta": "./graph.py:beta",
        }
    )

    assert configured_system_assistant_ids(graphs, namespace=namespace) == {
        str(uuid5(namespace, "alpha")),
        str(uuid5(namespace, "beta")),
    }


def test_configured_system_assistant_ids_skip_missing_or_empty_registry():
    assert configured_system_assistant_ids(None, namespace=NAMESPACE_DNS) == set()
    assert configured_system_assistant_ids("{}", namespace=NAMESPACE_DNS) == set()


def test_pre_runtime_repair_preserves_all_legacy_user_rows_and_versions():
    system_id = str(uuid4())
    forged_ids = [str(uuid4()) for _ in range(4)]
    ordinary_id = str(uuid4())
    store = {
        "assistants": [
            {
                "assistant_id": system_id,
                "metadata": {"created_by": "system"},
            },
            *[
                {
                    "assistant_id": assistant_id,
                    "metadata": {
                        "created_by": "system",
                        "user_id": "langgraph-studio-user",
                    },
                }
                for assistant_id in forged_ids
            ],
            {
                "assistant_id": ordinary_id,
                "metadata": {"created_by": "user", "user_id": "owner"},
            },
        ],
        "assistant_versions": [
            {
                "assistant_id": system_id,
                "version": 1,
                "metadata": {"created_by": "system"},
            },
            *[
                {
                    "assistant_id": assistant_id,
                    "version": version,
                    "metadata": {
                        "created_by": "system",
                        "user_id": "langgraph-studio-user",
                    },
                }
                for assistant_id in forged_ids
                for version in (1, 2)
            ],
            {
                "assistant_id": ordinary_id,
                "version": 1,
                "metadata": {"created_by": "user", "user_id": "owner"},
            },
        ],
    }

    result = repair_persisted_assistant_provenance(
        store,
        registered_system_ids={system_id},
    )

    assert result.removed_registered_assistants == 1
    assert result.removed_registered_versions == 1
    assert result.demoted_assistants == 4
    assert result.demoted_versions == 8
    assert [str(row["assistant_id"]) for row in store["assistants"]] == [*forged_ids, ordinary_id]
    assert len(store["assistant_versions"]) == 9
    assert all(row["metadata"]["created_by"] == "user" for row in store["assistants"])
    assert all(row["metadata"]["created_by"] == "user" for row in store["assistant_versions"])


def test_pre_runtime_repair_replaces_registered_id_even_with_forged_metadata():
    system_id = str(uuid4())
    store = {
        "assistants": [
            {
                "assistant_id": system_id,
                "metadata": {
                    "created_by": "user",
                    "user_id": "attacker",
                },
            }
        ],
        "assistant_versions": [
            {
                "assistant_id": system_id,
                "version": 1,
                "metadata": {
                    "created_by": "user",
                    "user_id": "attacker",
                },
            }
        ],
    }

    result = repair_persisted_assistant_provenance(
        store,
        registered_system_ids={system_id},
    )

    assert result.removed_registered_assistants == 1
    assert result.removed_registered_versions == 1
    assert store == {"assistants": [], "assistant_versions": []}


def test_pre_runtime_repair_skips_when_no_system_assistants_are_configured():
    marked_id = str(uuid4())
    store = {
        "assistants": [
            {
                "assistant_id": marked_id,
                "metadata": {"created_by": "system"},
            }
        ],
        "assistant_versions": [],
    }
    original = {
        "assistants": [dict(store["assistants"][0])],
        "assistant_versions": [],
    }

    result = repair_persisted_assistant_provenance(
        store,
        registered_system_ids=set(),
    )

    assert not result.changed
    assert store == original


def test_pre_runtime_repair_warns_when_registered_ids_match_no_persisted_rows(
    tmp_path: Path,
    caplog,
    monkeypatch,
):
    from langgraph.checkpoint.memory import PersistentDict

    persistence_path = tmp_path / ".langgraph_ops.pckl"
    store = PersistentDict(dict, filename=str(persistence_path))
    store["assistants"] = [
        {
            "assistant_id": str(uuid4()),
            "metadata": {
                "created_by": "system",
                "user_id": "langgraph-studio-user",
            },
        }
    ]
    store["assistant_versions"] = []
    store.sync()
    monkeypatch.setattr(
        "app.gateway.langgraph_studio.configured_system_assistant_ids",
        lambda _graphs_json: {"registered-assistant-id"},
    )

    with caplog.at_level(logging.WARNING, logger="app.gateway.langgraph_studio"):
        result = repair_local_dev_persistence_before_runtime(
            persistence_path=persistence_path,
            graphs_json=json.dumps({"registered_graph": "./graph.py:graph"}),
        )

    assert result.demoted_assistants == 1
    assert "matched no persisted registered assistant rows" in caplog.text


def test_langgraph_config_loads_the_pre_runtime_studio_app():
    config = json.loads((Path(__file__).resolve().parents[1] / "langgraph.json").read_text(encoding="utf-8"))

    assert config["http"]["app"].endswith("app/gateway/langgraph_studio.py:langgraph_app")
