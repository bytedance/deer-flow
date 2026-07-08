"""Unit tests for scripts/route_intent.py."""
import json
from pathlib import Path

import pytest

import route_intent as ri


@pytest.fixture
def routing_config(tmp_path):
    filters_dir = tmp_path / "config" / "filters"
    filters_dir.mkdir(parents=True)
    (filters_dir / "信贷.meta_data_filter.json").write_text(
        '{"method":"auto"}', encoding="utf-8"
    )
    (filters_dir / "信贷.metadata_condition.json").write_text(
        '{"logic":"and","conditions":[]}', encoding="utf-8"
    )
    (filters_dir / "制度.meta_data_filter.json").write_text(
        '{"method":"auto"}', encoding="utf-8"
    )
    (filters_dir / "制度.metadata_condition.json").write_text(
        '{"logic":"and","conditions":[]}', encoding="utf-8"
    )
    cfg = {
        "defaults": {
            "filter_mode": "search",
            "filters_dir": "config/filters",
            "department_top_k": 3,
            "department_min_score": 1,
        },
        "routes": [
            {
                "intent": "信贷",
                "label": "信贷知识库",
                "dataset_id": "kb-credit-001",
                "dataset_name": "信贷",
                "filter_mode": "search",
                "department_filter_enabled": True,
                "metadata_condition": "信贷.metadata_condition.json",
                "meta_data_filter": "信贷.meta_data_filter.json",
                "description": "贷款授信",
                "keywords": ["贷款", "利率", "授信"],
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
            },
            {
                "intent": "制度",
                "label": "制度知识库",
                "dataset_id": "kb-policy-001",
                "dataset_name": "制度",
                "filter_mode": "search",
                "department_filter_enabled": False,
                "metadata_condition": "制度.metadata_condition.json",
                "meta_data_filter": "制度.meta_data_filter.json",
                "description": "规章制度",
                "keywords": ["制度", "规章", "办法"],
                "departments": [],
            },
        ],
        "fallback": {"action": "ask_user", "message": "请澄清"},
    }
    path = tmp_path / "routing.json"
    path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return path


def test_score_prefers_credit_question(routing_config):
    routes = ri.parse_routes(ri.load_routing_config(routing_config))
    scores = ri.score_question("个人住房贷款利率怎么算？", routes)
    assert scores[0].intent == "信贷"
    assert scores[0].score >= 1


def test_score_prefers_policy_question(routing_config):
    routes = ri.parse_routes(ri.load_routing_config(routing_config))
    scores = ri.score_question("员工考勤制度里年假怎么申请？", routes)
    assert scores[0].intent == "制度"
    assert "制度" in scores[0].matched_keywords or scores[0].score >= 1


def test_resolve_returns_dataset_id(routing_config):
    config = ri.load_routing_config(routing_config)
    routes = ri.parse_routes(config)
    payload = ri.build_resolve_payload(
        question="贷款利率",
        intent="信贷",
        config=config,
        routes=routes,
    )
    assert payload["ok"] is True
    assert payload["dataset_id"] == "kb-credit-001"
    assert payload["dataset_ids"] == ["kb-credit-001"]
    assert "filters" in payload
    assert payload["filters"]["metadata_condition_path"].endswith(
        "config/filters/信贷.metadata_condition.json"
    )


def test_resolve_includes_rerank_id_from_defaults(routing_config):
    config = ri.load_routing_config(routing_config)
    routes = ri.parse_routes(config)
    config["defaults"]["rerank_enabled"] = True
    config["defaults"]["rerank_id"] = "BAAI/bge-reranker-v2-m3"
    payload = ri.build_resolve_payload(
        question="贷款利率",
        intent="信贷",
        config=config,
        routes=routes,
    )
    assert payload["rerank_id"] == "BAAI/bge-reranker-v2-m3"


def test_resolve_includes_retrieval_settings(routing_config):
    config = ri.load_routing_config(routing_config)
    routes = ri.parse_routes(config)
    config["defaults"]["recall_top_k"] = 64
    config["defaults"]["page_size"] = 10
    payload = ri.build_resolve_payload(
        question="贷款利率",
        intent="信贷",
        config=config,
        routes=routes,
    )
    assert payload["recall_top_k"] == 64
    assert payload["page_size"] == 10
    assert payload["max_citations"] == 10


def test_resolve_includes_runtime_department_filter(routing_config):
    config = ri.load_routing_config(routing_config)
    routes = ri.parse_routes(config)
    payload = ri.build_resolve_payload(
        question="零售消费贷利率",
        intent="信贷",
        config=config,
        routes=routes,
        explicit_departments=["零售", "对公"],
    )
    assert payload["filters"]["filter_enabled"] is True
    assert payload["filters"]["active_filter_source"] == "runtime_department"
    assert payload["filters"]["active_filter"]["manual"][0]["op"] == "in"


def test_resolve_ambiguous_fails(routing_config):
    config = ri.load_routing_config(routing_config)
    routes = ri.parse_routes(config)
    payload = ri.build_resolve_payload(
        question="帮我查一下",
        intent="ambiguous",
        config=config,
        routes=routes,
    )
    assert payload["ok"] is False


def test_cli_score(tmp_path, routing_config):
    out = tmp_path / "score.json"
    ri.main(["score", "--config", str(routing_config), "--question", "贷款", "--out", str(out)])
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["top_intent"] == "信贷"


def test_pick_intent_clear_winner(routing_config):
    routes = ri.parse_routes(ri.load_routing_config(routing_config))
    scores = ri.score_question("个人住房贷款利率怎么算？", routes)
    intent, reason = ri.pick_intent_from_scores(scores)
    assert intent == "信贷"
    assert reason in {"clear_winner", "score_gap_1", "score_gap_2", "score_gap_3"}


def test_pick_intent_ambiguous_on_tie(routing_config):
    routes = ri.parse_routes(ri.load_routing_config(routing_config))
    scores = ri.score_question("帮我查一下", routes)
    intent, reason = ri.pick_intent_from_scores(scores)
    assert intent is None
    assert reason in {"low_score", "tie"}


def test_cli_query_mock(tmp_path, routing_config, monkeypatch):
    monkeypatch.setenv("RAGFLOW_BASE_URL", "http://mock")
    monkeypatch.setenv("RAGFLOW_API_KEY", "key")
    out = tmp_path / "query.summary.json"
    rc = __import__("ragflow_client")
    fixture = str(
        Path(__file__).resolve().parents[2] / "example" / "mock_retrieval" / "chunks.json"
    )
    ri.main(
        [
            "query",
            "--config",
            str(routing_config),
            "--mock",
            "--mock-fixture",
            fixture,
            "--question",
            "零售消费贷款利率",
            "--quiet",
            "--out",
            str(out),
        ]
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["intent"] == "信贷"
    assert payload["citation_count"] >= 0
    retrieval = tmp_path / "query.retrieval.json"
    assert retrieval.exists()
    route = tmp_path / "route.json"
    assert route.exists()
