"""Unit tests for scripts/routing_utils.py."""
import json
from pathlib import Path

import routing_utils as ru


def test_resolve_rerank_id_from_defaults():
    config = {"defaults": {"rerank_id": "BAAI/bge-reranker-v2-m3"}}
    route_item = {"intent": "信贷"}
    assert ru.resolve_rerank_id(config, route_item) == "BAAI/bge-reranker-v2-m3"


def test_resolve_rerank_id_auto_default():
    config = {"defaults": {"rerank_enabled": True}}
    route_item = {"intent": "信贷"}
    assert ru.resolve_rerank_id(config, route_item) == "auto"


def test_compose_model_id():
    assert ru.compose_model_id(
        {
            "model_name": "BAAI/bge-reranker-v2-m3",
            "model_provider": "Builtin",
            "model_instance": "default",
        }
    ) == "BAAI/bge-reranker-v2-m3@Builtin"
    assert ru.compose_model_id(
        {
            "model_name": "my-rerank",
            "model_provider": "OpenAI-API-Compatible",
            "model_instance": "prod",
        }
    ) == "my-rerank@prod@OpenAI-API-Compatible"
    assert ru.compose_model_id(
        {
            "model_name": "bge-rerank-large",
            "model_provider": "HugginFace",
            "model_instance": "bge-rerank-large",
        }
    ) == "bge-rerank-large@bge-rerank-large@HugginFace"


def test_resolve_rerank_id_route_overrides_defaults():
    config = {"defaults": {"rerank_id": "bge-rerank-large"}}
    route_item = {"intent": "制度", "rerank_id": "other-rerank"}
    assert ru.resolve_rerank_id(config, route_item) == "other-rerank"


def test_resolve_rerank_id_disabled():
    config = {"defaults": {"rerank_enabled": False, "rerank_id": "bge-rerank-large"}}
    route_item = {"intent": "信贷"}
    assert ru.resolve_rerank_id(config, route_item) is None


def test_resolve_ragflow_credentials_from_dotenv(tmp_path, monkeypatch):
    monkeypatch.delenv("RAGFLOW_BASE_URL", raising=False)
    monkeypatch.delenv("RAGFLOW_API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "RAGFLOW_BASE_URL=http://dotenv:9380\nRAGFLOW_API_KEY=dotenv-key\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ru, "SKILL_ENV_FILE", env_file)
    url, key = ru.resolve_ragflow_credentials()
    assert url == "http://dotenv:9380"
    assert key == "dotenv-key"


def test_resolve_ragflow_credentials_cli_overrides_dotenv(tmp_path, monkeypatch):
    monkeypatch.delenv("RAGFLOW_BASE_URL", raising=False)
    monkeypatch.delenv("RAGFLOW_API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "RAGFLOW_BASE_URL=http://dotenv:9380\nRAGFLOW_API_KEY=dotenv-key\n",
        encoding="utf-8",
    )
    ru.load_skill_dotenv(env_file)
    url, key = ru.resolve_ragflow_credentials(
        base_url="http://cli:9380",
        api_key="cli-key",
    )
    assert url == "http://cli:9380"
    assert key == "cli-key"


def test_resolve_retrieval_settings_defaults():
    config = {"defaults": {"recall_top_k": 64, "page_size": 10, "similarity_threshold": 0.2}}
    route_item = {"intent": "信贷"}
    settings = ru.resolve_retrieval_settings(config, route_item)
    assert settings["recall_top_k"] == 64
    assert settings["page_size"] == 10
    assert settings["max_citations"] == 10


def test_resolve_run_retrieval_params_from_route():
    route = {"recall_top_k": 64, "page_size": 10, "max_citations": 10}
    params = ru.resolve_run_retrieval_params(route)
    assert params["recall_top_k"] == 64
    assert params["page_size"] == 10


def test_build_department_meta_data_filter_multi():
    payload = ru.build_department_meta_data_filter(
        "部门",
        ["零售金融部", "对公业务部"],
    )
    assert payload["manual"][0]["op"] == "in"
    assert len(payload["manual"][0]["value"]) == 2


def test_score_and_select_top_departments():
    departments = ru.parse_departments(
        {
            "departments": [
                {
                    "id": "零售",
                    "label": "零售金融部",
                    "metadata_value": "零售金融部",
                    "keywords": ["零售", "消费贷"],
                },
                {
                    "id": "对公",
                    "label": "对公业务部",
                    "metadata_value": "对公业务部",
                    "keywords": ["对公", "企业贷款"],
                },
                {
                    "id": "风控",
                    "label": "风险管理部",
                    "metadata_value": "风险管理部",
                    "keywords": ["风控", "审批"],
                },
            ]
        }
    )
    scores = ru.score_departments("个人消费贷利率怎么算？", departments)
    picked = ru.select_top_departments(scores, top_k=2, min_score=1)
    assert picked[0].id == "零售"
    assert len(picked) <= 2


def test_resolve_filters_runtime_department(tmp_path):
    skill_root = tmp_path
    filters_dir = skill_root / "config" / "filters"
    filters_dir.mkdir(parents=True)
    (filters_dir / "信贷.meta_data_filter.json").write_text("{}", encoding="utf-8")

    config = {
        "defaults": {
            "filter_mode": "search",
            "filters_dir": "config/filters",
            "department_metadata_field": "部门",
            "department_top_k": 2,
            "department_min_score": 1,
        }
    }
    route_item = {
        "intent": "信贷",
        "filter_mode": "search",
        "department_filter_enabled": True,
        "meta_data_filter": "信贷.meta_data_filter.json",
        "departments": [
            {
                "id": "零售",
                "label": "零售金融部",
                "metadata_value": "零售金融部",
                "keywords": ["零售", "消费贷"],
            },
            {
                "id": "对公",
                "label": "对公业务部",
                "metadata_value": "对公业务部",
                "keywords": ["对公"],
            },
        ],
    }

    filters = ru.resolve_filters_for_route(
        config,
        route_item,
        question="零售消费贷",
        explicit_departments=["零售", "对公"],
        skill_root=skill_root,
    )
    assert filters["filter_enabled"] is True
    assert filters["active_filter_source"] == "runtime_department"
    assert filters["active_filter"]["manual"][0]["op"] == "in"


def test_department_filter_disabled(tmp_path):
    skill_root = tmp_path
    config = {"defaults": {"filter_mode": "search", "filters_dir": "config/filters"}}
    route_item = {
        "intent": "制度",
        "filter_mode": "search",
        "department_filter_enabled": False,
        "departments": [],
    }
    filters = ru.resolve_filters_for_route(
        config,
        route_item,
        question="考勤制度",
        explicit_departments=["人事"],
        skill_root=skill_root,
    )
    assert filters["department_selection"]["enabled"] is False
    assert filters["filter_enabled"] is False
