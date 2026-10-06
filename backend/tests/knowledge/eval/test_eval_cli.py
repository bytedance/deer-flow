"""Tests for the rag-eval CLI shell (spec 2026-08-23 §6).

Coverage: argument parsing, the missing-key skip behavior (explicit exit 3,
never a fake green), exit-code passthrough, and the early error guards
(config ValueError / golden / baseline) — all without touching the engine,
Qdrant, or any external API.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

CLI_PATH = Path(__file__).resolve().parents[3] / "scripts" / "run_rag_eval.py"


def _load_cli():
    spec = importlib.util.spec_from_file_location("run_rag_eval", CLI_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cli = _load_cli()

KEYS = {"DASHSCOPE_EMBEDDING_API_KEY": "k1", "DASHSCOPE_RERANK_API_KEY": "k2"}


def _args(*extra: str) -> list[str]:
    return ["--golden", "g.jsonl", "--out", "out", "--kb-id", "kb1", *extra]


class TestParseArgs:
    def test_required_args(self):
        with pytest.raises(SystemExit):
            cli.parse_args(["--out", "out", "--kb-id", "kb1"])  # missing --golden
        with pytest.raises(SystemExit):
            cli.parse_args(["--golden", "g"])  # missing --out / --kb-id

    def test_defaults(self):
        args = cli.parse_args(_args())

        assert args.top_k == 5
        assert args.fail_threshold == pytest.approx(0.03)
        assert args.baseline is None

    def test_explicit_values(self):
        args = cli.parse_args(_args("--top-k", "10", "--fail-threshold", "0.05", "--baseline", "prev.json"))

        assert args.top_k == 10
        assert args.fail_threshold == pytest.approx(0.05)
        assert args.baseline == "prev.json"


class TestMissingRequiredKeys:
    def test_both_missing(self):
        assert cli.missing_required_keys({}) == list(cli.REQUIRED_ENV_KEYS)

    def test_all_present(self):
        assert cli.missing_required_keys(KEYS) == []

    def test_partial(self):
        assert cli.missing_required_keys({"DASHSCOPE_EMBEDDING_API_KEY": "k"}) == ["DASHSCOPE_RERANK_API_KEY"]


class TestSkipBehavior:
    def test_main_skips_without_keys(self, tmp_path, capsys, monkeypatch):
        # Task 0b: the skip path persists a skipped row (spec §3.1.1) — stubbed
        # here so the test never touches a real database; the real write is
        # covered in test_eval_persistence.py.
        persisted = []
        monkeypatch.setattr(cli, "_persist_quietly", lambda args, *, status, environment: persisted.append(status))
        out = tmp_path / "out"
        code = cli.main(["--golden", "g.jsonl", "--out", str(out), "--kb-id", "kb1"], environ={})

        assert code == 3  # EXIT_SKIPPED
        assert code != 0  # 不伪绿
        captured = capsys.readouterr()
        assert "skipped" in captured.out
        assert "DASHSCOPE_EMBEDDING_API_KEY" in captured.out
        assert not out.exists()  # 无副作用
        assert persisted == ["skipped"]


class TestExitCodeMapping:
    def test_run_result_passthrough(self, monkeypatch):
        monkeypatch.setattr(cli, "_run", lambda args, *, environment: 1)

        assert cli.main(_args(), environ=dict(KEYS)) == 1

    def test_ok_passthrough(self, monkeypatch):
        monkeypatch.setattr(cli, "_run", lambda args, *, environment: 0)

        assert cli.main(_args(), environ=dict(KEYS)) == 0


class TestAsyncMainGuards:
    def test_config_value_error_maps_to_skipped(self, monkeypatch, capsys):
        import deerflow.config.app_config as app_config_module

        def _raise():
            raise ValueError("Environment variable DEEPSEEK_API_KEY not found for config value $DEEPSEEK_API_KEY")

        monkeypatch.setattr(app_config_module, "get_app_config", _raise)

        assert cli._run(cli.parse_args(_args())) == 3
        assert "skipped" in capsys.readouterr().out

    def test_golden_load_error_maps_to_error(self, monkeypatch, tmp_path):
        import deerflow.config.app_config as app_config_module

        monkeypatch.setattr(app_config_module, "get_app_config", lambda: object())
        args = cli.parse_args(["--golden", str(tmp_path / "absent.jsonl"), "--out", str(tmp_path / "out"), "--kb-id", "kb1"])

        assert cli._run(args) == 2  # EXIT_ERROR

    def test_baseline_missing_file_maps_to_error(self, monkeypatch, tmp_path):
        import deerflow.config.app_config as app_config_module

        monkeypatch.setattr(app_config_module, "get_app_config", lambda: object())
        golden = tmp_path / "golden.jsonl"
        golden.write_text(
            json.dumps(
                {
                    "id": "q1",
                    "query": "q",
                    "expected_path": "vector",
                    "relevant_chunk_ids": ["e1b9e365f63747958337431dc755c620#0007"],
                    "relevant_entities": [],
                    "category": "fact",
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        args = cli.parse_args(["--golden", str(golden), "--out", str(tmp_path / "out"), "--kb-id", "kb1", "--baseline", str(tmp_path / "absent.json")])

        assert cli._run(args) == 2  # EXIT_ERROR，且未触达引擎初始化
