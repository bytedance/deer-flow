"""Chroma to pgvector migration script with KB-bound embedding support."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    import chromadb
except ImportError:
    chromadb = None  # type: ignore[assignment]


@dataclass
class KBReport:
    """Migration result for a single knowledge base."""

    kb_id: str
    kb_name: str
    collection_name: str
    embedding_model: str
    embedding_dim: int
    documents_total: int = 0
    documents_migrated: int = 0
    documents_skipped: int = 0
    documents_failed: int = 0
    chunks_total: int = 0
    chunks_migrated: int = 0
    estimated_tokens: int = 0
    estimated_cost_usd: float = 0.0
    duration_sec: float = 0.0
    error: str | None = None
    status: str = "pending"  # pending | success | failed | skipped


@dataclass
class MigrationReport:
    """Overall migration report."""

    kbs: list[KBReport] = field(default_factory=list)
    total_duration_sec: float = 0.0
    dry_run: bool = False

    def print_report(self) -> None:
        """Print a human-readable migration report."""
        print("\n" + "=" * 80)
        print("CHROMA → PGVECTOR MIGRATION REPORT" + (" (DRY RUN)" if self.dry_run else ""))
        print("=" * 80)

        success = [kb for kb in self.kbs if kb.status == "success"]
        failed = [kb for kb in self.kbs if kb.status == "failed"]
        skipped = [kb for kb in self.kbs if kb.status == "skipped"]

        for kb in self.kbs:
            symbol = "✓" if kb.status == "success" else "✗" if kb.status == "failed" else "⊘"
            print(f"\n  {symbol} {kb.kb_name} ({kb.kb_id})")
            print(f"    Collection: {kb.collection_name}")
            print(f"    Embedding: {kb.embedding_model} (dim={kb.embedding_dim})")
            print(f"    Documents: {kb.documents_migrated}/{kb.documents_total} "
                  f"(skipped={kb.documents_skipped}, failed={kb.documents_failed})")
            print(f"    Chunks: {kb.chunks_migrated}/{kb.chunks_total}")
            if self.dry_run:
                print(f"    Estimated: {kb.estimated_tokens} tokens, ${kb.estimated_cost_usd:.4f}")
            print(f"    Duration: {kb.duration_sec:.1f}s")
            if kb.error:
                print(f"    Error: {kb.error}")

        print("\n" + "-" * 80)
        total_docs = sum(kb.documents_migrated for kb in self.kbs)
        total_chunks = sum(kb.chunks_migrated for kb in self.kbs)
        total_tokens = sum(kb.estimated_tokens for kb in self.kbs)
        total_cost = sum(kb.estimated_cost_usd for kb in self.kbs)

        print(f"  Total: {len(self.kbs)} KBs "
              f"({len(success)} success, {len(failed)} failed, {len(skipped)} skipped)")
        print(f"  Documents: {total_docs} migrated")
        print(f"  Chunks: {total_chunks} migrated")
        if self.dry_run:
            print(f"  Estimated: {total_tokens} tokens, ${total_cost:.4f} total")
        print(f"  Duration: {self.total_duration_sec:.1f}s")
        print("=" * 80 + "\n")


def load_resume_state(resume_path: Path) -> set[str]:
    """Load set of already-processed KB IDs from resume file."""
    if not resume_path.exists():
        return set()
    try:
        data = json.loads(resume_path.read_text())
        return set(data.get("completed_kbs", []))
    except Exception:
        return set()


def save_resume_state(resume_path: Path, kb_id: str) -> None:
    """Mark a KB as completed in the resume file."""
    state = {}
    if resume_path.exists():
        try:
            state = json.loads(resume_path.read_text())
        except Exception:
            state = {}
    completed = set(state.get("completed_kbs", []))
    completed.add(kb_id)
    state["completed_kbs"] = sorted(completed)
    state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    resume_path.write_text(json.dumps(state, indent=2))


def estimate_embedding_cost(tokens: int, model: str) -> float:
    """Rough cost estimate for embedding generation."""
    pricing = {
        "text-embedding-3-small": 0.00002 / 1000,
        "text-embedding-3-large": 0.00013 / 1000,
        "text-embedding-ada-002": 0.00010 / 1000,
    }
    rate = pricing.get(model, 0.0001 / 1000)
    return tokens * rate


def migrate_knowledge_base(
    kb: Any,
    *,
    chroma_path: Path,
    pg_url: str,
    batch_size: int,
    rate_limit: float,
    dry_run: bool,
) -> KBReport:
    """Migrate a single knowledge base from Chroma to pgvector."""
    from sqlalchemy import create_engine, text

    report = KBReport(
        kb_id=kb.id,
        kb_name=kb.name,
        collection_name=kb.collection_name,
        embedding_model=kb.embedding_model or "text-embedding-3-small",
        embedding_dim=kb.embedding_dim or 1536,
    )
    start = time.monotonic()

    try:
        # Connect to Chroma
        if chromadb is None:
            raise ImportError("chromadb is required for RAG migration. Install with: uv add chromadb")

        chroma_client = chromadb.PersistentClient(path=str(chroma_path))
        tenant_id = kb.tenant_id
        chroma_col_name = f"{tenant_id}_{kb.collection_name}"

        try:
            chroma_col = chroma_client.get_collection(name=chroma_col_name)
        except Exception:
            report.status = "skipped"
            report.error = f"Chroma collection {chroma_col_name} not found"
            report.duration_sec = time.monotonic() - start
            return report

        # Get all documents from Chroma
        chroma_data = chroma_col.get()
        if not chroma_data or not chroma_data.get("ids"):
            report.status = "success"
            report.duration_sec = time.monotonic() - start
            logger.info("  %s: empty collection, nothing to migrate", kb.name)
            return report

        doc_ids = chroma_data["ids"]
        documents = chroma_data.get("documents", [])
        metadatas = chroma_data.get("metadatas", [])
        report.documents_total = len(doc_ids)

        # Estimate tokens (rough: 1 token ≈ 4 chars)
        total_chars = sum(len(doc or "") for doc in documents)
        report.estimated_tokens = total_chars // 4
        report.estimated_cost_usd = estimate_embedding_cost(report.estimated_tokens, report.embedding_model)

        if dry_run:
            report.status = "success"
            report.documents_migrated = report.documents_total
            report.chunks_migrated = report.documents_total
            report.duration_sec = time.monotonic() - start
            logger.info("  %s: dry run, would migrate %d documents", kb.name, report.documents_total)
            return report

        # Initialize embedding provider for this KB
        from deerflow.rag.embeddings import get_embedding_provider

        embedder = get_embedding_provider(model=report.embedding_model)

        # Connect to PostgreSQL
        engine = create_engine(pg_url)

        # Ensure table exists
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS knowledge_rag_chunks ("
                "  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),"
                "  tenant_id TEXT NOT NULL,"
                "  collection TEXT NOT NULL,"
                "  chunk_id TEXT NOT NULL,"
                "  content TEXT NOT NULL,"
                "  metadata JSONB DEFAULT '{}',"
                f"  embedding vector({report.embedding_dim}),"
                "  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()"
                ")"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_rag_tenant_collection"
                "  ON knowledge_rag_chunks (tenant_id, collection)"
            ))
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_rag_embedding_hnsw"
                "  ON knowledge_rag_chunks USING hnsw (embedding vector_cosine_ops)"
                "  WITH (m = 16, ef_construction = 64)"
            ))

        # Process in batches
        for i in range(0, len(doc_ids), batch_size):
            batch_ids = doc_ids[i:i + batch_size]
            batch_docs = documents[i:i + batch_size]
            batch_metas = metadatas[i:i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (len(doc_ids) + batch_size - 1) // batch_size

            logger.info("  %s: batch %d/%d (%d documents)",
                        kb.name, batch_num, total_batches, len(batch_ids))

            # Generate embeddings
            embeddings = embedder.embed(batch_docs)
            actual_dim = len(embeddings[0]) if embeddings else 0

            # Validate dimension
            if actual_dim and actual_dim != report.embedding_dim:
                report.status = "failed"
                report.error = f"Embedding dimension mismatch: expected {report.embedding_dim}, got {actual_dim}"
                report.duration_sec = time.monotonic() - start
                logger.error("  %s: %s", kb.name, report.error)
                return report

            # Insert into pgvector
            with engine.begin() as conn:
                for j, doc_id in enumerate(batch_ids):
                    conn.execute(text("""
                        INSERT INTO knowledge_rag_chunks (tenant_id, collection, chunk_id, content, metadata, embedding)
                        VALUES (:tid, :col, :cid, :content, :meta, :emb::vector)
                    """), {
                        "tid": tenant_id,
                        "col": kb.collection_name,
                        "cid": doc_id,
                        "content": batch_docs[j] or "",
                        "meta": json.dumps(batch_metas[j] or {}),
                        "emb": str(embeddings[j]),
                    })

            report.documents_migrated += len(batch_ids)
            report.chunks_migrated += len(batch_ids)

            # Rate limiting
            if rate_limit > 0 and i + batch_size < len(doc_ids):
                delay = 60.0 / rate_limit
                time.sleep(delay)

        report.status = "success"

    except Exception as e:
        report.status = "failed"
        report.error = str(e)
        logger.exception("  %s: migration failed", kb.name)

    report.duration_sec = time.monotonic() - start
    return report


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Migrate RAG data from Chroma to pgvector with KB-bound embedding support"
    )
    parser.add_argument("--chroma-path", required=True, type=Path,
                        help="Path to Chroma persistent storage directory")
    parser.add_argument("--postgres-url", required=True,
                        help="PostgreSQL connection URL")
    parser.add_argument("--database-path", required=True, type=Path,
                        help="Path to SQLite database file with knowledge_bases table")
    parser.add_argument("--batch-size", type=int, default=100,
                        help="Documents per batch (default: 100)")
    parser.add_argument("--rate-limit", type=float, default=0.0,
                        help="Batches per minute (0 = no limit)")
    parser.add_argument("--resume", action="store_true",
                        help="Resume from previous run (skip completed KBs)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Estimate work without migrating")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable verbose logging")

    args = parser.parse_args()

    # Setup logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
    )

    logger.info("Starting Chroma → pgvector migration")
    logger.info("  Chroma path: %s", args.chroma_path)
    logger.info("  Postgres URL: %s", args.postgres_url)
    logger.info("  Database path: %s", args.database_path)
    logger.info("  Batch size: %d", args.batch_size)
    logger.info("  Rate limit: %s", f"{args.rate_limit} batches/min" if args.rate_limit else "unlimited")
    logger.info("  Resume: %s", args.resume)
    logger.info("  Dry run: %s", args.dry_run)

    # Load knowledge bases from database
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from deerflow.persistence.knowledge_base.model import KnowledgeBaseRow

    db_url = f"sqlite:///{args.database_path}"
    engine = create_engine(db_url)

    with Session(engine) as session:
        kbs = session.execute(select(KnowledgeBaseRow)).scalars().all()

    logger.info("Found %d knowledge bases", len(kbs))

    # Load resume state
    resume_path = args.chroma_path.parent / "reindex_resume.json"
    completed_kbs = load_resume_state(resume_path) if args.resume else set()
    if completed_kbs:
        logger.info("Resuming: %d KBs already completed", len(completed_kbs))

    # Migrate each KB
    report = MigrationReport(dry_run=args.dry_run)
    overall_start = time.monotonic()

    for kb in kbs:
        if kb.id in completed_kbs:
            logger.info("Skipping %s (already completed)", kb.name)
            kb_report = KBReport(
                kb_id=kb.id,
                kb_name=kb.name,
                collection_name=kb.collection_name,
                embedding_model=kb.embedding_model or "text-embedding-3-small",
                embedding_dim=kb.embedding_dim or 1536,
                status="skipped",
            )
            report.kbs.append(kb_report)
            continue

        logger.info("Migrating %s...", kb.name)
        kb_report = migrate_knowledge_base(
            kb,
            chroma_path=args.chroma_path,
            pg_url=args.postgres_url,
            batch_size=args.batch_size,
            rate_limit=args.rate_limit,
            dry_run=args.dry_run,
        )
        report.kbs.append(kb_report)

        if kb_report.status == "success" and not args.dry_run:
            save_resume_state(resume_path, kb.id)

    report.total_duration_sec = time.monotonic() - overall_start
    report.print_report()

    # Exit code: 0 if all success/skipped, 1 if any failed
    failed = [kb for kb in report.kbs if kb.status == "failed"]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
