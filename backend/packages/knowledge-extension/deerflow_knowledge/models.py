"""ORM models for the RAG knowledge-base subsystem.

Four tables (spec §3.2–§3.5 + 2026-08-24 metrics visualization), all under the
extension-owned ``kb_`` prefix (D2):

- ``kb_knowledge_bases`` — one row per KB; Phase-1 is private-only but carries
  the ``owner_id`` / ``visibility`` hooks for the Phase-2 invite model.
- ``kb_documents`` — uploaded files with the indexing status machine
  (``uploaded → parsing → chunking → indexing → ready / failed``).
- ``kb_chunks`` — chunk text + per-chunk state columns; Qdrant only ever holds
  vectors + a ``chunk_id`` pointer.
- ``kb_eval_runs`` — evaluation run results (Layer 1 + Layer 2 metrics) for
  trend analysis and historical comparison (2026-08-24).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Index, Integer, String, Text, false, text
from sqlalchemy.orm import Mapped, mapped_column

from deerflow_knowledge.db import TABLE_PREFIX, Base


class KnowledgeBaseRow(Base):
    __tablename__ = f"{TABLE_PREFIX}knowledge_bases"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Phase 1: always "private". Phase 2 activates "shared" + kb_members.
    visibility: Mapped[str] = mapped_column(String(16), default="private")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    # Which embedding coordinate space this library's vectors live in (spec 2026-10-04 D2):
    # compact JSON of {provider, model, base_url}, written only by a full rebuild or the
    # library's first completed document. NULL = unstamped (legacy or mixed) — never a
    # claim of "current".
    embedding_identity: Mapped[str | None] = mapped_column(String(512), nullable=True)


class DocumentRow(Base):
    __tablename__ = f"{TABLE_PREFIX}documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kb_id: Mapped[str] = mapped_column(String(64), index=True)
    # Phase-1 mandatory field (spec §3.6): equals the KB owner for now; shared
    # KBs in Phase 2 give it real uploader semantics.
    uploader_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(512))
    size_bytes: Mapped[int] = mapped_column(Integer)
    storage_path: Mapped[str] = mapped_column(String(1024))
    status: Mapped[str] = mapped_column(String(16), default="uploaded", index=True)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    # Backfilled when indexing finishes; NULL renders as "—" in the doc list.
    chunk_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Per-path sub-status (phase-2 batch-1 P3, spec 2026-08-11 §5):
    # {"vector": pending/indexing/done/failed, "caption": .../degraded/...}.
    # NULL on legacy rows — the frontend renders no hover then.
    path_status: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # File content hash (Task 11): SHA-256 for duplicate detection;
    # written at upload time, NULL on legacy rows (no backfill).
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class ChunkRow(Base):
    __tablename__ = f"{TABLE_PREFIX}chunks"

    # "{doc_id}#0042" — deterministic, unique per document.
    chunk_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    doc_id: Mapped[str] = mapped_column(String(64), index=True)
    kb_id: Mapped[str] = mapped_column(String(64), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    heading_path: Mapped[list] = mapped_column(JSON, default=list)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    # Normalized entity names (spec §3.2); kept for schema stability — the
    # first phase has no graph leg to backfill them.
    entities: Mapped[list] = mapped_column(JSON, default=list)
    # Extract state machine for resume: pending → done / empty / failed.
    extract_status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    extract_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Phase-3 Batch-1 P2: manual edit timestamp (audit trail for slice editing)
    last_edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EvalRunRow(Base):
    """Evaluation run result (2026-08-24 metrics visualization spec).

    Persists Layer2Report output for trend analysis and historical comparison.
    Layer 1 metrics (deterministic IR) and Layer 2 metrics (RAGAS + arch-specific)
    are stored as JSON for flexibility.
    """

    __tablename__ = f"{TABLE_PREFIX}eval_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # run_id
    kb_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16))  # completed / error / skipped

    # Layer 1 metrics: {category: {hit_rate, recall_at_k, mrr, path_accuracy}, summary: {...}}
    layer1_metrics: Mapped[dict] = mapped_column(JSON)

    # Layer 2 metrics: {ragas: {faithfulness, ...}, arch_specific: {citation_precision, ...}}
    layer2_metrics: Mapped[dict] = mapped_column(JSON)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Optional integrations
    langfuse_trace_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Baseline comparison (if compared against a baseline run)
    baseline_diff: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Run environment (spec v3): local / ci / nightly. CI runs stay out of the
    # default latest/trend read sets (``include_ci=true`` opts them back in).
    environment: Mapped[str] = mapped_column(String(16), default="local", server_default=text("'local'"))

    # Baseline marker (§3.1.3): the trend API's threshold line reads this row,
    # and ``--baseline auto`` diffs against it.
    is_baseline: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())

    __table_args__ = (
        # At most one baseline row per KB: ``--mark-baseline`` clears the old
        # marker and sets the new one in a single transaction; this partial
        # unique index is the DB-level backstop. Must live in ORM
        # ``__table_args__`` (not just migration 0018) because the empty-DB
        # bootstrap path runs ``create_all`` + ``stamp head`` and never
        # executes the migration.
        Index(
            "uq_eval_runs_kb_baseline",
            "kb_id",
            unique=True,
            sqlite_where=text("is_baseline = true"),
            postgresql_where=text("is_baseline = true"),
        ),
    )
