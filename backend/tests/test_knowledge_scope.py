import json

import pytest
from pydantic import ValidationError

from deerflow.knowledge_scope import (
    KNOWLEDGE_SCOPE_KEY,
    KnowledgeScope,
    canonicalize_knowledge_scope,
    execution_scope,
)


def test_all_and_disabled_canonicalize_without_selection_fields() -> None:
    assert canonicalize_knowledge_scope({"version": 1, "mode": "all"}) == {
        "version": 1,
        "mode": "all",
    }
    assert canonicalize_knowledge_scope({"version": 1, "mode": "disabled"}) == {
        "version": 1,
        "mode": "disabled",
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"version": 2, "mode": "all"},
        {"version": 1, "mode": "all", "future": True},
        {"version": 1, "mode": "all", "dataset_ids": ["dataset-a"]},
        {"version": 1, "mode": "disabled", "display": {"datasets": []}},
        {"version": 1, "mode": "selected", "dataset_ids": []},
        {
            "version": 1,
            "mode": "selected",
            "dataset_ids": ["dataset-a"],
            "document_filters": [{"dataset_id": "dataset-a", "document_ids": []}],
        },
        {
            "version": 1,
            "mode": "selected",
            "dataset_ids": ["dataset-a"],
            "document_filters": [
                {"dataset_id": "dataset-a", "document_ids": ["doc-a"]},
                {"dataset_id": "dataset-a", "document_ids": ["doc-b"]},
            ],
        },
        {
            "version": 1,
            "mode": "selected",
            "dataset_ids": ["dataset-a"],
            "document_filters": [{"dataset_id": "dataset-b", "document_ids": ["doc-a"]}],
        },
    ],
)
def test_invalid_scope_shapes_are_rejected(payload: dict) -> None:
    with pytest.raises(ValidationError):
        canonicalize_knowledge_scope(payload)


def test_selected_scope_trims_and_stably_deduplicates_ids() -> None:
    scope = canonicalize_knowledge_scope(
        {
            "version": 1,
            "mode": "selected",
            "dataset_ids": [" dataset-a ", "dataset-b", "dataset-a"],
            "document_filters": [
                {
                    "dataset_id": " dataset-b ",
                    "document_ids": [" doc-1 ", "doc-2", "doc-1"],
                }
            ],
        }
    )

    assert scope == {
        "version": 1,
        "mode": "selected",
        "dataset_ids": ["dataset-a", "dataset-b"],
        "document_filters": [{"dataset_id": "dataset-b", "document_ids": ["doc-1", "doc-2"]}],
    }


def test_execution_scope_drops_untrusted_display_snapshot() -> None:
    scope = canonicalize_knowledge_scope(
        {
            "version": 1,
            "mode": "selected",
            "dataset_ids": ["dataset-a"],
            "display": {"datasets": [{"id": "dataset-a", "name": "Agriculture", "documents": []}]},
        }
    )

    assert execution_scope(scope) == {
        "version": 1,
        "mode": "selected",
        "dataset_ids": ["dataset-a"],
    }
    assert KNOWLEDGE_SCOPE_KEY == "knowledge_scope"


@pytest.mark.parametrize(
    "payload",
    [
        {
            "version": 1,
            "mode": "selected",
            "dataset_ids": ["dataset-a"],
            "display": {"datasets": [{"id": "dataset-b", "name": "Other"}]},
        },
        {
            "version": 1,
            "mode": "selected",
            "dataset_ids": ["dataset-a"],
            "document_filters": [{"dataset_id": "dataset-a", "document_ids": ["doc-a"]}],
            "display": {
                "datasets": [
                    {
                        "id": "dataset-a",
                        "name": "Agriculture",
                        "documents": [{"id": "doc-b", "name": "Other.pdf"}],
                    }
                ]
            },
        },
        {
            "version": 1,
            "mode": "selected",
            "dataset_ids": ["dataset-a"],
            "display": {
                "datasets": [
                    {"id": "dataset-a", "name": "First"},
                    {"id": "dataset-a", "name": "Duplicate"},
                ]
            },
        },
    ],
)
def test_display_must_be_unique_and_related_to_execution_selection(payload: dict) -> None:
    with pytest.raises(ValidationError):
        canonicalize_knowledge_scope(payload)


def test_scope_capacity_limits_are_rejected_without_truncation() -> None:
    with pytest.raises(ValidationError):
        canonicalize_knowledge_scope(
            {
                "version": 1,
                "mode": "selected",
                "dataset_ids": [f"dataset-{index}" for index in range(101)],
            }
        )

    with pytest.raises(ValidationError):
        canonicalize_knowledge_scope(
            {
                "version": 1,
                "mode": "selected",
                "dataset_ids": ["dataset-a"],
                "document_filters": [
                    {
                        "dataset_id": "dataset-a",
                        "document_ids": [f"doc-{index}" for index in range(1001)],
                    }
                ],
            }
        )

    with pytest.raises(ValidationError):
        canonicalize_knowledge_scope(
            {
                "version": 1,
                "mode": "selected",
                "dataset_ids": ["x" * 257],
            }
        )


def test_display_capacity_and_canonical_json_byte_limit_are_enforced() -> None:
    with pytest.raises(ValidationError):
        canonicalize_knowledge_scope(
            {
                "version": 1,
                "mode": "selected",
                "dataset_ids": [f"dataset-{index}" for index in range(21)],
                "display": {"datasets": [{"id": f"dataset-{index}", "name": f"Dataset {index}"} for index in range(21)]},
            }
        )

    oversized = {
        "version": 1,
        "mode": "selected",
        "dataset_ids": ["dataset-a"],
        "document_filters": [
            {
                "dataset_id": "dataset-a",
                "document_ids": [f"doc-{index}-{'x' * 240}" for index in range(300)],
            }
        ],
    }
    assert len(json.dumps(oversized, ensure_ascii=False).encode()) > 64 * 1024
    with pytest.raises(ValidationError):
        canonicalize_knowledge_scope(oversized)


def test_model_rejects_more_than_fifty_display_documents_and_long_names() -> None:
    document_ids = [f"doc-{index}" for index in range(51)]
    with pytest.raises(ValidationError):
        KnowledgeScope.model_validate(
            {
                "version": 1,
                "mode": "selected",
                "dataset_ids": ["dataset-a"],
                "document_filters": [{"dataset_id": "dataset-a", "document_ids": document_ids}],
                "display": {
                    "datasets": [
                        {
                            "id": "dataset-a",
                            "name": "Agriculture",
                            "documents": [{"id": document_id, "name": f"Document {index}"} for index, document_id in enumerate(document_ids)],
                        }
                    ]
                },
            }
        )

    with pytest.raises(ValidationError):
        canonicalize_knowledge_scope(
            {
                "version": 1,
                "mode": "selected",
                "dataset_ids": ["dataset-a"],
                "display": {
                    "datasets": [
                        {"id": "dataset-a", "name": "名" * 257},
                    ]
                },
            }
        )
