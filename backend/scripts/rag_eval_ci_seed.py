"""Seed the no-cloud CI's fixture library from the fixed material (RFC v3 §8.2).

Builds (or rebuilds) a knowledge base whose doc ids derive from the material
bytes — ``sha256(relpath \\0 content)[:32]`` — so chunk ids (``<doc_id>#NNNN``)
are stable across runs and can serve as golden anchors. The real pipeline runs:
local parse → chunk → embed (recorded/replayed) → Qdrant upsert, through the
same ``KnowledgeService`` + worker wiring the gateway uses.

Usage (from ``backend/``):

    uv run python scripts/rag_eval_ci_seed.py --kb-id <32hex> [--owner-id <id>] \
        [--materials tests/fixtures/rag_eval/materials] [--chunks-out <path.jsonl>] \
        [--no-reset]

Prints a JSON summary (kb id + per-document ids) to stdout for the workflow /
recording scripts. ``--chunks-out`` additionally dumps every stored chunk
(id/index/heading/text) for golden annotation.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path

DEFAULT_MATERIALS = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "rag_eval" / "materials"


def deterministic_doc_id(relative_name: str, content: bytes) -> str:
    return hashlib.sha256(relative_name.encode("utf-8") + b"\0" + content).hexdigest()[:32]


def deterministic_kb_id(slug: str = "rag-eval-ci-kb") -> str:
    return hashlib.sha256(slug.encode("utf-8")).hexdigest()[:32]


def material_files(materials_dir: Path) -> list[Path]:
    return sorted(path for path in materials_dir.rglob("*") if path.is_file() and path.name != "README.md" and path.suffix != ".py")


async def seed(args: argparse.Namespace) -> dict:
    from deerflow_knowledge.migrations.runner import run_knowledge_migrations
    from deerflow_knowledge.services.knowledge_service import KnowledgeService
    from deerflow_knowledge.store import KnowledgeStore
    from deerflow_knowledge.vector_store import get_vector_store
    from deerflow_knowledge.worker import KnowledgeIndexWorker

    from deerflow.config.app_config import get_app_config
    from deerflow.config.paths import get_paths
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config

    config = get_app_config()
    await init_engine_from_config(config.database)
    try:
        session_factory = get_session_factory()
        if session_factory is None:
            raise RuntimeError("the seed needs a durable database session factory")
        await run_knowledge_migrations(session_factory)

        store = KnowledgeStore(session_factory)
        vector_store = get_vector_store()
        data_dir = get_paths().base_dir / "data"
        rag = config.rag
        worker = KnowledgeIndexWorker(
            store=store,
            vector_store=vector_store,
            concurrency=rag.worker_concurrency,
            sweep_enabled=False,
            data_dir=data_dir,
        )
        service = KnowledgeService(store=store, vector_store=vector_store, worker=worker, data_dir=data_dir)

        if args.reset:
            existing = await store.get_kb(args.kb_id)
            if existing is not None:
                await service.delete_kb_cascade(kb_id=args.kb_id)

        await store.create_kb(kb_id=args.kb_id, owner_id=args.owner_id, name="RAG Eval CI fixture")
        await worker.start()
        documents = []
        try:
            for path in material_files(Path(args.materials)):
                content = path.read_bytes()
                relative = path.name
                doc_id = deterministic_doc_id(relative, content)
                await service.upload_document(kb_id=args.kb_id, uploader_id=args.owner_id, filename=relative, content=content, doc_id=doc_id)
                documents.append({"name": relative, "doc_id": doc_id})
            await worker.wait_idle()
        finally:
            await worker.stop()

        statuses = {doc["name"]: (await store.get_document(doc["doc_id"]))["status"] for doc in documents}
        not_ready = {name: status for name, status in statuses.items() if status != "ready"}
        if not_ready:
            raise RuntimeError(f"material documents did not reach 'ready': {not_ready}")

        if args.chunks_out:
            target = Path(args.chunks_out)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("w", encoding="utf-8", newline="\n") as handle:
                for doc in documents:
                    offset = 0
                    while True:
                        chunks = await store.list_chunks(doc["doc_id"], offset=offset, limit=200)
                        for chunk in chunks:
                            handle.write(
                                json.dumps(
                                    {
                                        "doc_id": doc["doc_id"],
                                        "doc_name": doc["name"],
                                        "chunk_id": chunk["chunk_id"],
                                        "chunk_index": chunk["chunk_index"],
                                        "heading_path": chunk.get("heading_path") or [],
                                        "text": chunk["text"],
                                    },
                                    ensure_ascii=False,
                                )
                                + "\n"
                            )
                        if len(chunks) < 200:
                            break
                        offset += len(chunks)
        return {"kb_id": args.kb_id, "owner_id": args.owner_id, "documents": documents}
    finally:
        await close_engine()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed the no-cloud RAG eval CI fixture library from fixed material.")
    parser.add_argument("--kb-id", default=None, help="Fixture KB id (default: deterministic sha256[:32] of 'rag-eval-ci-kb').")
    parser.add_argument("--owner-id", default="rag-eval-ci", help="KB owner (the eval runs as the owner).")
    parser.add_argument("--materials", default=str(DEFAULT_MATERIALS), help="Material directory (default: tests/fixtures/rag_eval/materials).")
    parser.add_argument("--chunks-out", default=None, help="Optional JSONL dump of stored chunks (golden annotation aid).")
    parser.add_argument("--no-reset", action="store_true", help="Do not drop an existing fixture KB first (default: reset).")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    args.reset = not args.no_reset
    if not args.kb_id:
        args.kb_id = deterministic_kb_id()
    summary = asyncio.run(seed(args))
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
