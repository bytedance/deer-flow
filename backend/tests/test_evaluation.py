"""Tests for evaluation framework — metrics, dataset loading, judge, and runner."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from deerflow.config.evaluation_config import (
    EvaluationConfig,
    get_evaluation_config,
    load_evaluation_config_from_dict,
    reset_evaluation_config,
)
from deerflow.evaluation.dataset import EvalCase, load_dataset
from deerflow.evaluation.judge import LLMJudge
from deerflow.evaluation.metrics import (
    calculate_mrr,
    calculate_ndcg,
    calculate_precision_at_k,
    calculate_recall_at_k,
)
from deerflow.evaluation.runner import CaseResult, EvalReport, EvalRunner


class TestEvaluationConfig:
    def test_default_config(self):
        reset_evaluation_config()
        config = get_evaluation_config()
        assert config.enabled is False
        assert config.judge_model == ""
        assert "accuracy" in config.metrics
        assert config.ci_threshold == 0.7

    def test_load_from_dict(self):
        load_evaluation_config_from_dict({
            "enabled": True,
            "judge_model": "gpt-4",
            "metrics": ["accuracy", "safety"],
            "ci_threshold": 0.8,
        })
        config = get_evaluation_config()
        assert config.enabled is True
        assert config.judge_model == "gpt-4"
        assert config.metrics == ["accuracy", "safety"]
        assert config.ci_threshold == 0.8

    def test_reset(self):
        load_evaluation_config_from_dict({"enabled": True})
        reset_evaluation_config()
        config = get_evaluation_config()
        assert config.enabled is False


class TestMetrics:
    def test_mrr_single_hit(self):
        ranked = [[0, 1, 0]]
        assert calculate_mrr(ranked) == 0.5

    def test_mrr_first_position(self):
        ranked = [[1, 0, 0]]
        assert calculate_mrr(ranked) == 1.0

    def test_mrr_no_hit(self):
        ranked = [[0, 0, 0]]
        assert calculate_mrr(ranked) == 0.0

    def test_mrr_multiple_queries(self):
        ranked = [[1, 0], [0, 1], [0, 0]]
        assert calculate_mrr(ranked) == pytest.approx((1.0 + 0.5 + 0.0) / 3)

    def test_mrr_empty(self):
        assert calculate_mrr([]) == 0.0

    def test_ndcg_perfect(self):
        ranked = [[3.0, 2.0, 1.0]]
        ideal = [[3.0, 2.0, 1.0]]
        assert calculate_ndcg(ranked, ideal) == pytest.approx(1.0)

    def test_ndcg_empty(self):
        assert calculate_ndcg([], []) == 0.0

    def test_ndcg_zero_idcg(self):
        ranked = [[0.0, 0.0]]
        ideal = [[0.0, 0.0]]
        assert calculate_ndcg(ranked, ideal) == 0.0

    def test_recall_at_k_perfect(self):
        ranked = [[1, 2, 3, 4, 5]]
        relevant = [{1, 2, 3}]
        assert calculate_recall_at_k(ranked, relevant, k=3) == 1.0

    def test_recall_at_k_partial(self):
        ranked = [[1, 2, 3, 4, 5]]
        relevant = [{1, 2, 6, 7}]
        assert calculate_recall_at_k(ranked, relevant, k=3) == 0.5

    def test_recall_at_k_empty_relevant(self):
        ranked = [[1, 2, 3]]
        relevant = [set()]
        assert calculate_recall_at_k(ranked, relevant, k=3) == 1.0

    def test_recall_at_k_empty_input(self):
        assert calculate_recall_at_k([], [], k=3) == 0.0

    def test_precision_at_k_perfect(self):
        ranked = [[1, 2, 3]]
        relevant = [{1, 2, 3}]
        assert calculate_precision_at_k(ranked, relevant, k=3) == 1.0

    def test_precision_at_k_partial(self):
        ranked = [[1, 2, 3, 4, 5]]
        relevant = [{1, 2, 6, 7}]
        assert calculate_precision_at_k(ranked, relevant, k=4) == 0.5

    def test_precision_at_k_empty(self):
        assert calculate_precision_at_k([], [], k=3) == 0.0


class TestDataset:
    def test_load_dataset(self):
        content = (
            '{"conversation": [{"role": "user", "content": "hello"}], "expected_tools": ["bash"], "min_score": 0.8}\n'
            '{"conversation": [{"role": "user", "content": "search"}], "expected_topics": ["results"]}\n'
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
            f.write(content)
            tmp_path = f.name

        try:
            cases = load_dataset(tmp_path)
            assert len(cases) == 2
            assert cases[0].expected_tools == ["bash"]
            assert cases[0].min_score == 0.8
            assert cases[1].expected_topics == ["results"]
            assert cases[1].min_score == 0.7
        finally:
            Path(tmp_path).unlink()

    def test_load_dataset_skips_comments_and_blanks(self):
        content = (
            "# comment line\n"
            "\n"
            '{"conversation": [], "min_score": 0.5}\n'
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8") as f:
            f.write(content)
            tmp_path = f.name

        try:
            cases = load_dataset(tmp_path)
            assert len(cases) == 1
        finally:
            Path(tmp_path).unlink()

    def test_eval_case_from_dict_defaults(self):
        case = EvalCase.from_dict({})
        assert case.conversation == []
        assert case.expected_tools == []
        assert case.min_score == 0.7


class TestLLMJudge:
    def test_no_model_returns_zero_scores(self):
        load_evaluation_config_from_dict({"judge_model": "", "metrics": ["accuracy", "completeness"]})
        judge = LLMJudge()
        scores = judge.evaluate("test response")
        assert scores == {"accuracy": 0.0, "completeness": 0.0}

    def test_parse_scores(self):
        load_evaluation_config_from_dict({"judge_model": "", "metrics": ["accuracy", "completeness"]})
        judge = LLMJudge()
        text = '{"accuracy": {"score": 0.9, "justification": "good"}, "completeness": {"score": 0.7, "justification": "ok"}}'
        scores = judge._parse_scores(text)
        assert scores["accuracy"] == 0.9
        assert scores["completeness"] == 0.7

    def test_parse_scores_flat(self):
        load_evaluation_config_from_dict({"judge_model": "", "metrics": ["accuracy"]})
        judge = LLMJudge()
        scores = judge._parse_scores('{"accuracy": 0.85}')
        assert scores["accuracy"] == 0.85

    def test_parse_scores_invalid_json(self):
        load_evaluation_config_from_dict({"judge_model": "", "metrics": ["accuracy"]})
        judge = LLMJudge()
        scores = judge._parse_scores("not json at all")
        assert scores["accuracy"] == 0.0

    def test_parse_scores_with_markdown_wrapper(self):
        load_evaluation_config_from_dict({"judge_model": "", "metrics": ["accuracy"]})
        judge = LLMJudge()
        text = '```json\n{"accuracy": {"score": 0.95, "justification": "perfect"}}\n```'
        scores = judge._parse_scores(text)
        assert scores["accuracy"] == 0.95

    def test_evaluate_with_mock_model(self):
        load_evaluation_config_from_dict({"judge_model": "test-model", "metrics": ["accuracy"]})
        judge = LLMJudge()
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.content = '{"accuracy": {"score": 0.88, "justification": "good"}}'
        mock_model.invoke.return_value = mock_response

        with patch("deerflow.evaluation.judge.create_chat_model", return_value=mock_model):
            scores = judge.evaluate("test response", expected="expected", criteria="be accurate")
        assert scores["accuracy"] == 0.88

    def test_evaluate_model_error_returns_zeros(self):
        load_evaluation_config_from_dict({"judge_model": "test-model", "metrics": ["accuracy"]})
        judge = LLMJudge()
        with patch("deerflow.evaluation.judge.create_chat_model", side_effect=RuntimeError("model down")):
            scores = judge.evaluate("test response")
        assert scores["accuracy"] == 0.0


class TestEvalReport:
    def test_to_dict(self):
        report = EvalReport(
            total_cases=2,
            passed=1,
            failed=1,
            errors=0,
            pass_rate=0.5,
            avg_overall_score=0.75,
            dimension_averages={"accuracy": 0.8},
            case_results=[
                CaseResult(case_index=0, passed=True, scores={"accuracy": 0.9}, overall_score=0.9, min_score=0.7),
                CaseResult(case_index=1, passed=False, scores={"accuracy": 0.6}, overall_score=0.6, min_score=0.7),
            ],
            duration_seconds=1.5,
        )
        d = report.to_dict()
        assert d["total_cases"] == 2
        assert d["pass_rate"] == 0.5
        assert len(d["case_results"]) == 2

    def test_save(self):
        report = EvalReport(total_cases=1, passed=1, pass_rate=1.0)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            tmp_path = f.name

        try:
            report.save(tmp_path)
            with open(tmp_path, encoding="utf-8") as f:
                data = json.load(f)
            assert data["total_cases"] == 1
        finally:
            Path(tmp_path).unlink()


class TestEvalRunner:
    def test_run_passing_case(self):
        load_evaluation_config_from_dict({"judge_model": "test-model", "metrics": ["accuracy"]})
        runner = EvalRunner()

        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.content = '{"accuracy": {"score": 0.9, "justification": "good"}}'
        mock_model.invoke.return_value = mock_response

        def agent(msg):
            return f"response to: {msg}"

        case = EvalCase(
            conversation=[{"role": "user", "content": "hello"}],
            expected_tools=["bash"],
            min_score=0.7,
        )

        with patch("deerflow.evaluation.judge.create_chat_model", return_value=mock_model):
            report = runner.run([case], agent)

        assert report.total_cases == 1
        assert report.passed == 1
        assert report.failed == 0
        assert report.pass_rate == 1.0

    def test_run_failing_case(self):
        load_evaluation_config_from_dict({"judge_model": "test-model", "metrics": ["accuracy"]})
        runner = EvalRunner()

        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.content = '{"accuracy": {"score": 0.3, "justification": "bad"}}'
        mock_model.invoke.return_value = mock_response

        case = EvalCase(conversation=[{"role": "user", "content": "test"}], min_score=0.7)

        with patch("deerflow.evaluation.judge.create_chat_model", return_value=mock_model):
            report = runner.run([case], lambda msg: "bad response")

        assert report.failed == 1
        assert report.pass_rate == 0.0

    def test_run_agent_error(self):
        load_evaluation_config_from_dict({"judge_model": "", "metrics": ["accuracy"]})
        runner = EvalRunner()

        def failing_agent(msg):
            raise RuntimeError("agent crash")

        case = EvalCase(conversation=[{"role": "user", "content": "test"}])
        report = runner.run([case], failing_agent)

        assert report.errors == 1
        assert report.case_results[0].error == "agent crash"

    def test_run_empty_dataset(self):
        runner = EvalRunner()
        report = runner.run([], lambda msg: "")
        assert report.total_cases == 0
        assert report.pass_rate == 0.0

    def test_compare(self):
        load_evaluation_config_from_dict({"judge_model": "", "metrics": ["accuracy"]})
        runner = EvalRunner()
        case = EvalCase(conversation=[{"role": "user", "content": "test"}])
        bl, ca = runner.compare([case], lambda msg: "baseline", lambda msg: "candidate")
        assert bl.total_cases == 1
        assert ca.total_cases == 1

    def test_dimension_averages(self):
        load_evaluation_config_from_dict({"judge_model": "test-model", "metrics": ["accuracy", "completeness"]})
        runner = EvalRunner()

        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.content = '{"accuracy": {"score": 0.8}, "completeness": {"score": 0.6}}'
        mock_model.invoke.return_value = mock_response

        case = EvalCase(conversation=[{"role": "user", "content": "test"}], min_score=0.5)

        with patch("deerflow.evaluation.judge.create_chat_model", return_value=mock_model):
            report = runner.run([case], lambda msg: "ok")

        assert report.dimension_averages["accuracy"] == 0.8
        assert report.dimension_averages["completeness"] == 0.6
