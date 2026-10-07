"""Record the fixed combination's external outputs (RFC v3 §8.2 备料).

One real pass — real embedding / rerank / caption services, real parse+chunk+
index+recall pipeline — whose external calls are captured into a JSONL fixture.
Afterwards the CI can rerun the identical pipeline offline: the replay service
serves these outputs by input fingerprint while everything else stays real.
The script also emits the CI's fixture configs, pinned to the values this run
actually used (models, dimension, caption parameters), so record and replay
cannot drift apart silently.

Usage (from ``backend/``):

    uv run python scripts/rag_eval_record.py \
        --real-config <path to the real config.yaml> \
        --real-rag-config <path to the real rag_config.json> \
        --golden tests/fixtures/rag_eval/golden.jsonl \
        [--dotenv <path to .env with the real keys>] \
        [--out tests/fixtures/rag_eval/ci] [--qdrant-url http://127.0.0.1:6399] \
        [--kb-id <32hex>] [--skip-eval] [--keep-scratch]

``--skip-eval`` records only the index-side calls and dumps the seeded chunks
(``<out>/chunks.jsonl``) — the annotation pass that comes before the golden is
written. The default run records everything and executes the eval CLI against
the real services.

The scratch config (real keys from the rag config file + the models entry)
lives in a system temp dir and is deleted on success unless ``--keep-scratch``;
nothing secret is ever written under the repository.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR / "scripts"))
sys.path.insert(0, str(BACKEND_DIR / "tests"))


def _load_dotenv(path: str | None) -> None:
    if not path:
        return
    from dotenv import load_dotenv

    load_dotenv(path, override=False)


def _compose_scratch(args: argparse.Namespace) -> Path:
    """Write the scratch config pair: real model/rag values, isolated storage.

    The rag config is the real file with ``vlm_model`` pinned to the caption
    entry this recording declares (``--vlm-model``), so the fixed combination's
    caption model is explicit and resolvable from the scratch ``models:`` list.
    """
    import yaml

    scratch = Path(args.scratch) if args.scratch else Path(tempfile.mkdtemp(prefix="rag-eval-record-"))
    scratch.mkdir(parents=True, exist_ok=True)

    real_config_path = Path(args.real_config)
    real_config = yaml.safe_load(real_config_path.read_text(encoding="utf-8")) or {}

    # Start from the real file wholesale (it is valid by construction — required
    # sections like sandbox stay) and only swap the storage coordinates: the
    # scratch sqlite and the isolated Qdrant, never the live ones.
    scratch_config = dict(real_config)
    scratch_config["database"] = {"backend": "sqlite", "sqlite_dir": str(scratch / "db")}
    rag_section = dict(scratch_config.get("rag") or {})
    rag_section["qdrant_url"] = args.qdrant_url
    scratch_config["rag"] = rag_section
    (scratch / "config.record.yaml").write_text(yaml.safe_dump(scratch_config, allow_unicode=True, sort_keys=False), encoding="utf-8")

    real_rag = json.loads(Path(args.real_rag_config).read_text(encoding="utf-8"))
    real_rag["vlm_model"] = args.vlm_model
    (scratch / "rag_config.record.json").write_text(json.dumps(real_rag, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    os.environ["DEER_FLOW_HOME"] = str(scratch / "home")
    os.environ["DEER_FLOW_CONFIG_PATH"] = str(scratch / "config.record.yaml")
    os.environ["DEER_FLOW_RAG_CONFIG_PATH"] = str(scratch / "rag_config.record.json")
    return scratch


def _emit_ci_configs(out_dir: Path, config, vlm_target) -> dict:
    """Write config.ci.yaml + rag_config.ci.json pinned to this run's values."""
    import yaml

    rag = config.rag
    replay_base = "http://127.0.0.1:8642"
    use_class = "langchain_anthropic:ChatAnthropic" if vlm_target.dialect == "anthropic" else "langchain_openai:ChatOpenAI"

    ci_config = {
        "database": {"backend": "sqlite", "sqlite_dir": ".rag-eval-ci/data"},
        # AppConfig 必填段：CI 无需执行沙箱，声明本地 provider 占位即可。
        "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
        "rag": {
            "qdrant_url": "$QDRANT_URL",
            "caption_max_tokens": rag.caption_max_tokens,
            "caption_temperature": rag.caption_temperature,
            "vlm_thinking": bool(rag.vlm_thinking),
        },
        "models": [
            {
                "name": "rag-eval-replay-vlm",
                "use": use_class,
                "model": vlm_target.model,
                "base_url": replay_base,
                "api_key": "replay-placeholder",
            }
        ],
    }
    (out_dir / "config.ci.yaml").write_text(yaml.safe_dump(ci_config, allow_unicode=True, sort_keys=False), encoding="utf-8")

    ci_rag = {
        "embedding_provider": rag.embedding_provider,
        "embedding_model": rag.embedding_model,
        "embedding_base_url": replay_base,
        "embedding_api_key": "replay-placeholder",
        "embedding_dimension": rag.embedding_dimension or 1024,
        "embedding_sparse_source": rag.embedding_sparse_source,
        "rerank_provider": rag.rerank_provider,
        "rerank_model": rag.rerank_model,
        "rerank_base_url": replay_base,
        "rerank_api_key": "replay-placeholder",
        "vlm_model": "rag-eval-replay-vlm",
        "mineru_api_token": "replay-placeholder",
    }
    (out_dir / "rag_config.ci.json").write_text(json.dumps(ci_rag, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return ci_rag


def run(args: argparse.Namespace) -> int:
    from rag_eval_ci.capture import Recorder, install

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    scratch = _compose_scratch(args)
    print(f"rag-eval-record: scratch config at {scratch}")

    from deerflow_knowledge.vlm_target import resolve_vlm_target

    from deerflow.config.app_config import get_app_config

    config = get_app_config()
    # A config without a usable caption target is a hard error here — the image
    # material must be captioned by the real model during the recording pass.
    vlm_target = resolve_vlm_target(config)

    recorder = Recorder()
    install(recorder)

    from rag_eval_ci_seed import deterministic_kb_id, seed

    kb_id = args.kb_id or deterministic_kb_id()
    seed_args = SimpleNamespace(
        kb_id=kb_id,
        owner_id=args.owner_id,
        materials=str(Path(args.materials)),
        chunks_out=str(out_dir / "chunks.jsonl"),
        reset=True,
    )
    summary = asyncio.run(seed(seed_args))
    print(f"rag-eval-record: seeded {len(summary['documents'])} documents into kb {kb_id}")

    if not args.skip_eval:
        import run_rag_eval

        # The CLI's credential precheck reads the *environment*; this run's keys
        # live in the rag config file (the resolver's first stop), so mirror them
        # into the child env — memory only, never printed, never written.
        eval_env = dict(os.environ)
        if config.rag.embedding_api_key:
            eval_env.setdefault("DASHSCOPE_EMBEDDING_API_KEY", config.rag.embedding_api_key)
        if config.rag.rerank_api_key:
            eval_env.setdefault("DASHSCOPE_RERANK_API_KEY", config.rag.rerank_api_key)

        eval_out = out_dir / "real-run"
        code = run_rag_eval.main(
            [
                "--golden",
                str(Path(args.golden)),
                "--out",
                str(eval_out),
                "--kb-id",
                kb_id,
                "--candidate-limit",
                "20",
                "--environment",
                "local",
            ],
            environ=eval_env,
        )
        print(f"rag-eval-record: real eval run exit={code} (report at {eval_out})")
        if code not in (0, 1):
            raise RuntimeError(f"the real eval run failed with exit {code}; the recording is not complete")

    entries = recorder.write(out_dir / "recording.jsonl.gz")
    ci_rag = _emit_ci_configs(out_dir, config, vlm_target)

    from rag_eval_ci.replay import material_fingerprint

    manifest = {
        "version": 1,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "fingerprint": material_fingerprint(args.materials),
        "kb_id": kb_id,
        "entries": entries,
        "combination": {
            "embedding_provider": config.rag.embedding_provider,
            "embedding_model": config.rag.embedding_model,
            "embedding_dimension": config.rag.embedding_dimension or 1024,
            "embedding_sparse_source": config.rag.embedding_sparse_source,
            "rerank_provider": config.rag.rerank_provider,
            "rerank_model": config.rag.rerank_model,
            "vlm_dialect": vlm_target.dialect,
            "vlm_model": vlm_target.model,
            "caption_max_tokens": config.rag.caption_max_tokens,
            "caption_temperature": config.rag.caption_temperature,
            "vlm_thinking": bool(config.rag.vlm_thinking),
        },
        "ci_rag_config": ci_rag,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"rag-eval-record: recorded {entries} entries → {out_dir / 'recording.jsonl.gz'}")

    if not args.keep_scratch:
        shutil.rmtree(scratch, ignore_errors=True)
    else:
        print(f"rag-eval-record: scratch kept at {scratch}")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record the fixed combination's external outputs and emit the CI fixtures.")
    parser.add_argument("--real-config", required=True, help="The real config.yaml (models entries incl. the caption VLM).")
    parser.add_argument("--real-rag-config", required=True, help="The real rag_config.json (embedding/rerank/VLM values).")
    parser.add_argument("--golden", default=str(BACKEND_DIR / "tests" / "fixtures" / "rag_eval" / "golden.jsonl"))
    parser.add_argument("--materials", default=str(BACKEND_DIR / "tests" / "fixtures" / "rag_eval" / "materials"))
    parser.add_argument("--out", default=str(BACKEND_DIR / "tests" / "fixtures" / "rag_eval" / "ci"))
    parser.add_argument("--dotenv", default=None, help="Optional .env with the real keys the config's $VARs reference.")
    parser.add_argument("--vlm-model", default="qwen3.7-flash", help="models: entry used for captioning during the recording (must be vision-capable).")
    parser.add_argument("--qdrant-url", default="http://127.0.0.1:6399", help="Isolated Qdrant for the recording run (never the live one).")
    parser.add_argument("--kb-id", default=None)
    parser.add_argument("--owner-id", default="rag-eval-ci")
    parser.add_argument("--scratch", default=None, help="Scratch directory (default: a fresh system temp dir).")
    parser.add_argument("--skip-eval", action="store_true", help="Index-side only: seed + chunk dump (pre-golden annotation pass).")
    parser.add_argument("--keep-scratch", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    _load_dotenv(args.dotenv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
