"""Tests for the Layer 2 ragas-eval CLI shell (spec 2026-08-23 §8).

Same contract family as the Layer 1 CLI: argument parsing, the missing-key
explicit skip (exit 3, never a fake green), the early error guards — plus the
Layer-2-only rules: quality numbers NEVER affect the exit code, and a missing
ragas install degrades to an evaluator-None skip instead of an error.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import yaml

from deerflow.config.app_config import AppConfig, RagConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig

CLI_PATH = Path(__file__).resolve().parents[3] / "scripts" / "run_ragas_eval.py"


def _load_cli():
    spec = importlib.util.spec_from_file_location("run_ragas_eval", CLI_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cli = _load_cli()

KEYS = {"DASHSCOPE_EMBEDDING_API_KEY": "k1", "DASHSCOPE_RERANK_API_KEY": "k2"}


def _config(*names: str, default_model: str | None = None, judge_model: str | None = None) -> AppConfig:
    """A real config, so a wrong judge name reaches the real factory's not-found raise."""
    return AppConfig(
        models=[ModelConfig(name=name, display_name=name, description=None, use="langchain_openai:ChatOpenAI", model=f"{name}-wire", api_key="test-key", supports_thinking=False) for name in names],
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
        rag=RagConfig(default_model=default_model, judge_model=judge_model),
    )


def _golden(tmp_path: Path) -> Path:
    golden = tmp_path / "golden.jsonl"
    golden.write_text(
        json.dumps({"id": "q1", "query": "q", "expected_path": "vector", "relevant_chunk_ids": [], "relevant_entities": [], "category": "fact"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return golden


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

        assert args.limit is None
        assert args.agent_model is None
        assert args.judge_model is None

    def test_explicit_values(self):
        args = cli.parse_args(_args("--limit", "3", "--agent-model", "deepseek-v4-flash", "--judge-model", "dashscope:qwen3.8-max"))

        assert args.limit == 3
        assert args.agent_model == "deepseek-v4-flash"
        assert args.judge_model == "dashscope:qwen3.8-max"


class TestMissingRequiredKeys:
    def test_both_missing(self):
        assert cli.missing_required_keys({}) == list(cli.REQUIRED_ENV_KEYS)

    def test_all_present(self):
        assert cli.missing_required_keys(KEYS) == []


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
        assert not out.exists()  # 无副作用
        assert persisted == ["skipped"]


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

        assert cli._run(args) == 2  # EXIT_ERROR，且未触达引擎初始化


class TestJudgeModelSelection:
    def test_config_model_name_delegates_to_factory(self, monkeypatch):
        import deerflow.models.factory as factory

        seen = {}

        def _create(name=None, **kwargs):
            seen["name"] = name
            return object()

        monkeypatch.setattr(factory, "create_chat_model", _create)

        cli._build_judge_llm("qwen3.7-flash", config=_config("qwen3.7-flash"))
        assert seen["name"] == "qwen3.7-flash"

    def test_default_none_falls_back_to_the_rag_default(self, monkeypatch):
        """Same contract as the factory's own test (spec 2026-09-23 D3).

        ``None`` resolves through RAG's order before the factory is called, so the delegate
        receives a concrete entry name instead of ``None``.
        """
        from types import SimpleNamespace

        import deerflow.models.factory as factory

        seen = {}
        monkeypatch.setattr(factory, "create_chat_model", lambda name=None, **kwargs: seen.setdefault("name", name) or object())
        config = SimpleNamespace(
            models=[SimpleNamespace(name="A"), SimpleNamespace(name="B")],
            rag=SimpleNamespace(judge_model=None, default_model="B", judge_thinking=False),
            # The shared wrapper's entry gate looks the entry up when thinking is on (spec 2026-10-03).
            get_model_config=lambda name: SimpleNamespace(supports_thinking=True),
        )

        cli._build_judge_llm(None, config=config)
        assert seen["name"] == "B"

    def test_the_direct_branch_is_gone_from_the_script(self):
        """Source pin (D9): the CLI no longer knows the prefix, its env key or its exception."""
        source = CLI_PATH.read_text(encoding="utf-8")

        assert "JudgeKeyMissingError" not in source
        assert "DASHSCOPE_JUDGE_API_KEY" not in source
        assert "dashscope:" not in source


class TestJudgeNameMapping:
    """A wrong judge name is a usage error: readable sentence, one ``error`` row, exit 2 (D9 乙).

    It used to be a *skip* (exit 3, a row marked ``skipped``), which the nightly job treated as
    an explicit pass — the reversal is the point of R27/R28③.
    """

    def test_a_wrong_judge_name_maps_to_a_readable_error_row(self, monkeypatch, capsys, tmp_path):
        import deerflow.config.app_config as app_config_module

        monkeypatch.setattr(app_config_module, "get_app_config", lambda: _config("A"))
        spy = AsyncMock()
        monkeypatch.setattr(cli, "_persist_eval_run", spy)
        monkeypatch.setattr("deerflow.persistence.engine.init_engine_from_config", AsyncMock())
        reached: list[str] = []

        class _StoreStub:
            async def get_kb(self, kb_id):
                reached.append(kb_id)
                raise AssertionError("the run must stop at the judge mapping, not continue into the store")

        monkeypatch.setattr("deerflow.knowledge.store.get_knowledge_store", lambda: _StoreStub())
        args = cli.parse_args(["--golden", str(_golden(tmp_path)), "--out", str(tmp_path / "out"), "--kb-id", "kb1", "--judge-model", "dashscope:qwen3.8-max"])

        code = cli._run(args)

        assert code == cli.EXIT_ERROR == 2  # not 1, not EXIT_SKIPPED
        captured = capsys.readouterr()
        assert "Model dashscope:qwen3.8-max not found in config" in captured.err
        assert captured.out == ""  # a refusal, not a report
        # Exactly one row, marked as a failure — the same invariant the other error paths keep.
        assert spy.await_count == 1
        assert spy.await_args.kwargs["status"] == "error"
        assert reached == []

    def test_a_non_not_found_value_error_is_not_mapped(self, monkeypatch, capsys, tmp_path):
        """R28⑤: only the not-found sentence is mapped. A bug inside the factory must keep
        escaping instead of being laundered into a tidy "your name is wrong" exit 2."""
        import deerflow.config.app_config as app_config_module

        monkeypatch.setattr(app_config_module, "get_app_config", lambda: _config("A"))

        def _boom(*args, **kwargs):
            raise ValueError("factory exploded")

        monkeypatch.setattr(cli, "_build_judge_llm", _boom)
        spy = AsyncMock()
        monkeypatch.setattr(cli, "_persist_eval_run", spy)
        args = cli.parse_args(["--golden", str(_golden(tmp_path)), "--out", str(tmp_path / "out"), "--kb-id", "kb1", "--judge-model", "whatever"])

        with pytest.raises(ValueError, match="factory exploded"):
            cli._run(args)

        assert spy.await_count == 0

    def test_the_mapping_only_accepts_the_factorys_own_sentence(self):
        """One wording, pinned by equality: the recognizer is fed the sentence the *real*
        factory raises — and nothing that merely resembles it (spec 2026-09-23 D9/R6)."""
        from deerflow.knowledge.eval import factory as eval_factory
        from deerflow.knowledge.model_target import is_model_not_found_error

        with pytest.raises(ValueError) as excinfo:
            eval_factory.build_judge_llm("ghost-entry", config=_config("A"))

        assert is_model_not_found_error(excinfo.value) is True
        for near_miss in ("Model A not found in configs", "model A not found in config", "Model A missing from config", "boom"):
            assert is_model_not_found_error(ValueError(near_miss)) is False

    def test_the_wrong_judge_name_exits_two_in_a_subprocess(self, tmp_path):
        """The module's own ``sys.exit(main())`` contract, end to end: 2, never 1 or 3.

        The child gets its own config (whose sqlite dir stays inside ``tmp_path``, so nothing
        touches a real database) and no judge env key: the name alone decides.
        """
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            yaml.safe_dump(
                {
                    "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
                    "models": [{"name": "A", "use": "langchain_openai:ChatOpenAI", "model": "a-wire"}],
                    "rag": {},
                    "database": {"backend": "sqlite", "sqlite_dir": str(tmp_path / "data")},
                }
            ),
            encoding="utf-8",
        )
        extensions_path = tmp_path / "extensions_config.json"
        extensions_path.write_text(json.dumps({"mcpServers": {}, "skills": {}}), encoding="utf-8")
        env = {
            **os.environ,
            **KEYS,
            "DEER_FLOW_CONFIG_PATH": str(config_path),
            "DEER_FLOW_EXTENSIONS_CONFIG_PATH": str(extensions_path),
        }
        env.pop("DASHSCOPE_JUDGE_API_KEY", None)
        env.pop("DASHSCOPE_API_KEY", None)

        proc = subprocess.run(
            [sys.executable, str(CLI_PATH), "--golden", str(_golden(tmp_path)), "--out", str(tmp_path / "out"), "--kb-id", "kb1", "--judge-model", "dashscope:qwen3.8-max"],
            cwd=str(tmp_path),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )

        assert proc.returncode == 2, proc.stderr
        assert proc.returncode not in (1, 3)
        assert "Model dashscope:qwen3.8-max not found in config" in proc.stderr
        # …and it stopped at the judge: a later failure would also exit 2 and fake this green.
        assert "knowledge base not found" not in proc.stderr


class TestEnvFileLoading:
    def test_root_env_fallback_then_backend_override(self, monkeypatch):
        import dotenv

        calls = []
        monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **kw: calls.append((a, kw)))

        cli._load_env_files()

        assert len(calls) == 2
        # First pass: repo-root .env as fallback (no override).
        assert str(calls[0][0][0]).endswith(".env")
        assert "backend" not in str(calls[0][0][0])
        assert calls[0][1].get("override") in (None, False)
        # Second pass: backend/.env wins.
        assert calls[1][1].get("override") is True


class TestRagasEvaluatorAssembly:
    def test_returns_none_when_ragas_not_installed(self, monkeypatch):
        # sys.modules entry None makes any ``import ragas`` raise ImportError.
        monkeypatch.setitem(sys.modules, "ragas", None)
        monkeypatch.setitem(sys.modules, "ragas.llms", None)
        monkeypatch.setitem(sys.modules, "ragas.embeddings", None)

        assert cli._build_ragas_evaluator(judge_llm=object()) is None

    def test_wraps_judge_with_bypass_n(self, monkeypatch):
        """DashScope judges reject ``n>1`` (answer_relevancy strictness=3 requests
        3 completions), so the wrapper must set ragas' ``bypass_n`` — ragas then
        sends n separate single-completion calls instead of one n-completion call."""

        captured: dict = {}

        class FakeWrapper:
            def __init__(self, llm, **kwargs):
                captured["bypass_n"] = kwargs.get("bypass_n")

        class FakeEmbeddingsWrapper:
            def __init__(self, embeddings):
                pass

        fake_ragas_llms = type(sys)("ragas.llms")
        fake_ragas_llms.LangchainLLMWrapper = FakeWrapper
        fake_ragas_embed = type(sys)("ragas.embeddings")
        fake_ragas_embed.LangchainEmbeddingsWrapper = FakeEmbeddingsWrapper
        monkeypatch.setitem(sys.modules, "ragas.llms", fake_ragas_llms)
        monkeypatch.setitem(sys.modules, "ragas.embeddings", fake_ragas_embed)
        monkeypatch.setattr(cli, "_DashScopeLangChainEmbeddings", lambda *a, **kw: object())

        evaluator = cli._build_ragas_evaluator(judge_llm=object())
        assert evaluator is not None
        assert captured["bypass_n"] is True
