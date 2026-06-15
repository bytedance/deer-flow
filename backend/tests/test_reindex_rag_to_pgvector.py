"""Tests for reindex_rag_to_pgvector.py migration script."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestResumeState:
    """Tests for resume state persistence."""

    def test_load_nonexistent_returns_empty(self):
        from scripts.reindex_rag_to_pgvector import load_resume_state

        with tempfile.TemporaryDirectory() as tmpdir:
            result = load_resume_state(Path(tmpdir) / "resume.json")
            assert result == set()

    def test_save_and_load_roundtrip(self):
        from scripts.reindex_rag_to_pgvector import load_resume_state, save_resume_state

        with tempfile.TemporaryDirectory() as tmpdir:
            resume_path = Path(tmpdir) / "resume.json"

            save_resume_state(resume_path, "kb-1")
            save_resume_state(resume_path, "kb-2")

            result = load_resume_state(resume_path)
            assert result == {"kb-1", "kb-2"}

    def test_save_idempotent(self):
        from scripts.reindex_rag_to_pgvector import load_resume_state, save_resume_state

        with tempfile.TemporaryDirectory() as tmpdir:
            resume_path = Path(tmpdir) / "resume.json"

            save_resume_state(resume_path, "kb-1")
            save_resume_state(resume_path, "kb-1")

            result = load_resume_state(resume_path)
            assert result == {"kb-1"}

    def test_corrupted_file_returns_empty(self):
        from scripts.reindex_rag_to_pgvector import load_resume_state

        with tempfile.TemporaryDirectory() as tmpdir:
            resume_path = Path(tmpdir) / "resume.json"
            resume_path.write_text("not valid json{{{")

            result = load_resume_state(resume_path)
            assert result == set()


class TestCostEstimation:
    """Tests for embedding cost estimation."""

    def test_small_model_pricing(self):
        from scripts.reindex_rag_to_pgvector import estimate_embedding_cost

        cost = estimate_embedding_cost(1_000_000, "text-embedding-3-small")
        assert cost == pytest.approx(0.02, abs=0.001)

    def test_large_model_pricing(self):
        from scripts.reindex_rag_to_pgvector import estimate_embedding_cost

        cost = estimate_embedding_cost(1_000_000, "text-embedding-3-large")
        assert cost == pytest.approx(0.13, abs=0.001)

    def test_unknown_model_uses_default(self):
        from scripts.reindex_rag_to_pgvector import estimate_embedding_cost

        cost = estimate_embedding_cost(1_000_000, "unknown-model")
        assert cost > 0

    def test_zero_tokens(self):
        from scripts.reindex_rag_to_pgvector import estimate_embedding_cost

        cost = estimate_embedding_cost(0, "text-embedding-3-small")
        assert cost == 0.0


class TestReport:
    """Tests for migration report output."""

    def test_report_prints_without_error(self, capsys):
        from scripts.reindex_rag_to_pgvector import KBReport, MigrationReport

        report = MigrationReport()
        report.kbs.append(KBReport(
            kb_id="kb-1",
            kb_name="Test KB",
            collection_name="test-collection",
            embedding_model="text-embedding-3-small",
            embedding_dim=1536,
            documents_total=10,
            documents_migrated=8,
            documents_skipped=2,
            chunks_total=10,
            chunks_migrated=8,
            status="success",
            duration_sec=5.2,
        ))
        report.total_duration_sec = 5.2

        report.print_report()
        captured = capsys.readouterr()
        assert "Test KB" in captured.out
        assert "success" not in captured.out.lower() or "8/10" in captured.out

    def test_report_shows_failures(self, capsys):
        from scripts.reindex_rag_to_pgvector import KBReport, MigrationReport

        report = MigrationReport()
        report.kbs.append(KBReport(
            kb_id="kb-1",
            kb_name="Failed KB",
            collection_name="fail-collection",
            embedding_model="text-embedding-3-small",
            embedding_dim=1536,
            status="failed",
            error="Dimension mismatch",
        ))
        report.total_duration_sec = 1.0

        report.print_report()
        captured = capsys.readouterr()
        assert "Failed KB" in captured.out
        assert "Dimension mismatch" in captured.out

    def test_dry_run_report_shows_estimates(self, capsys):
        from scripts.reindex_rag_to_pgvector import KBReport, MigrationReport

        report = MigrationReport(dry_run=True)
        report.kbs.append(KBReport(
            kb_id="kb-1",
            kb_name="Dry KB",
            collection_name="dry-collection",
            embedding_model="text-embedding-3-small",
            embedding_dim=1536,
            documents_total=100,
            estimated_tokens=50000,
            estimated_cost_usd=1.0,
            status="success",
        ))
        report.total_duration_sec = 0.1

        report.print_report()
        captured = capsys.readouterr()
        assert "DRY RUN" in captured.out
        assert "Estimated" in captured.out
        assert "$1.0000" in captured.out


class TestMigrateKnowledgeBase:
    """Tests for single KB migration logic."""

    def test_skips_missing_chroma_collection(self):
        """Missing Chroma collection should result in skipped status."""
        from scripts.reindex_rag_to_pgvector import migrate_knowledge_base

        kb = MagicMock()
        kb.id = "kb-1"
        kb.name = "Test KB"
        kb.collection_name = "missing-collection"
        kb.tenant_id = "tenant-1"
        kb.embedding_model = "text-embedding-3-small"
        kb.embedding_dim = 1536

        with patch("scripts.reindex_rag_to_pgvector.chromadb") as mock_chromadb:
            mock_client = MagicMock()
            mock_chromadb.PersistentClient.return_value = mock_client
            mock_client.get_collection.side_effect = Exception("Collection not found")

            report = migrate_knowledge_base(
                kb,
                chroma_path=Path("/fake/path"),
                pg_url="sqlite:///:memory:",
                batch_size=10,
                rate_limit=0,
                dry_run=False,
            )

            assert report.status == "skipped"
            assert "not found" in report.error

    def test_empty_collection_succeeds(self):
        """Empty Chroma collection should succeed with zero documents."""
        from scripts.reindex_rag_to_pgvector import migrate_knowledge_base

        kb = MagicMock()
        kb.id = "kb-1"
        kb.name = "Empty KB"
        kb.collection_name = "empty-collection"
        kb.tenant_id = "tenant-1"
        kb.embedding_model = "text-embedding-3-small"
        kb.embedding_dim = 1536

        with patch("scripts.reindex_rag_to_pgvector.chromadb") as mock_chromadb:
            mock_client = MagicMock()
            mock_chromadb.PersistentClient.return_value = mock_client

            mock_col = MagicMock()
            mock_col.get.return_value = {"ids": []}
            mock_client.get_collection.return_value = mock_col

            report = migrate_knowledge_base(
                kb,
                chroma_path=Path("/fake/path"),
                pg_url="sqlite:///:memory:",
                batch_size=10,
                rate_limit=0,
                dry_run=False,
            )

            assert report.status == "success"
            assert report.documents_total == 0

    def test_dry_run_skips_embedding(self):
        """Dry run mode should estimate costs without calling embedding API."""
        from scripts.reindex_rag_to_pgvector import migrate_knowledge_base

        kb = MagicMock()
        kb.id = "kb-1"
        kb.name = "Dry KB"
        kb.collection_name = "dry-collection"
        kb.tenant_id = "tenant-1"
        kb.embedding_model = "text-embedding-3-small"
        kb.embedding_dim = 1536

        with patch("scripts.reindex_rag_to_pgvector.chromadb") as mock_chromadb:
            mock_client = MagicMock()
            mock_chromadb.PersistentClient.return_value = mock_client

            mock_col = MagicMock()
            mock_col.get.return_value = {
                "ids": ["doc-1", "doc-2"],
                "documents": ["Hello world", "Test document"],
                "metadatas": [{}, {}],
            }
            mock_client.get_collection.return_value = mock_col

            with patch("deerflow.rag.embeddings.get_embedding_provider") as mock_get_embedder:
                report = migrate_knowledge_base(
                    kb,
                    chroma_path=Path("/fake/path"),
                    pg_url="sqlite:///:memory:",
                    batch_size=10,
                    rate_limit=0,
                    dry_run=True,
                )

                assert report.status == "success"
                assert report.documents_total == 2
                assert report.documents_migrated == 2
                assert report.estimated_tokens > 0
                assert report.estimated_cost_usd > 0
                # Embedder should not be called in dry-run mode
                mock_get_embedder.assert_not_called()
