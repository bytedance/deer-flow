"""Replay service for the no-cloud RAG evaluation CI (RFC v3 §8.2).

Speaks the same provider dialects the extension's clients use — DashScope's
text-embedding path, the compatible rerank path, and OpenAI/Anthropic chat
completions — and answers every request from the recording taken during
material preparation, matched by ``rag_eval_ci.replay.key_for_request``. A
cache miss is a 500 with a loud message: the fixture must be re-recorded,
never silently answered with an empty vector.

The CI starts this next to Qdrant and points the rag config's base URLs at it;
the pipeline code is untouched, so parse/chunk/index/recall/RRF/rerank
application all run for real in the CI.

Usage (from ``backend/``):

    uv run python scripts/rag_eval_replay_server.py \
        --recording tests/fixtures/rag_eval/ci/recording.jsonl.gz \
        [--materials tests/fixtures/rag_eval/materials] \
        [--host 127.0.0.1] [--port 8642]

``--materials`` verifies the recording's fingerprint against the material on
disk and refuses to serve on a mismatch (inputs changed → re-record).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR / "tests"))

# 模块级 import：``from __future__ import annotations`` 把注解变成字符串，FastAPI 解析
# 签名时要能在函数 globals 里找到 ``Request``/``JSONResponse``（函数内 import 会解析不到，
# 被当成 query 参数 ⇒ 422）。
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from rag_eval_ci.replay import ReplayMiss, key_for_request, load_recording, material_fingerprint, remap_rerank_response  # noqa: E402


def _manifest_fingerprint(recording_path: Path) -> str | None:
    manifest_path = recording_path.parent / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8")).get("fingerprint")
    except (json.JSONDecodeError, OSError):
        return None


def build_app(recording_path: Path, materials_dir: Path | None):
    recording = load_recording(recording_path)
    if materials_dir is not None:
        recorded = _manifest_fingerprint(recording_path)
        current = material_fingerprint(materials_dir)
        if recorded is not None and recorded != current:
            raise RuntimeError(f"material fingerprint mismatch: recording {recorded[:16]}… vs material {current[:16]}… — the material changed since the recording; re-record before replaying")

    app = FastAPI(title="RAG eval replay service")

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok", "entries": len(recording)}

    @app.post("/{full_path:path}")
    async def replay(full_path: str, request: Request):
        body = await request.json()
        path = f"/{full_path}"
        try:
            key = key_for_request(path, body)
        except Exception as exc:  # noqa: BLE001 — unknown call kind is as fatal as a miss here
            return JSONResponse(status_code=500, content={"detail": f"replay cannot serve {path}: {exc}"})
        try:
            entry = recording[key]
        except KeyError:
            raise ReplayMiss(f"no recorded output for {path} (key {key[:16]}…) — the fixture is stale; re-record") from None
        if "documents" in entry:
            # Rerank: indices are remapped onto this request's (tie-unstable) order.
            return JSONResponse(content=remap_rerank_response(entry, [str(doc) for doc in body.get("documents") or []]))
        return JSONResponse(content=entry["response"])

    @app.exception_handler(ReplayMiss)
    async def _miss_handler(_request: Request, exc: ReplayMiss):
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    return app


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve recorded external outputs for the no-cloud RAG eval CI.")
    parser.add_argument("--recording", required=True, help="Path to the recorded JSONL fixture.")
    parser.add_argument("--materials", default=None, help="Material directory to fingerprint-check against the recording manifest.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8642)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    import uvicorn

    args = parse_args(argv)
    app = build_app(Path(args.recording), Path(args.materials) if args.materials else None)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
