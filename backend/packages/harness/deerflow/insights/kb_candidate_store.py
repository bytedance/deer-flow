"""KB candidate storage with tenant isolation.

Stores KB candidates as JSON files in insights/{tenant_id}/kb_candidates/.
Provides methods to save, retrieve, promote, and dismiss candidates.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from deerflow.insights.models import KBCandidate
from deerflow.config.paths import Paths

logger = logging.getLogger(__name__)


class KBCandidateStore:
    """JSON file storage for KB candidates with tenant isolation."""

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self._paths = Paths(base_dir)

    def _candidate_path(self, tenant_id: str, ticket_id: str) -> Path:
        """Get the file path for a candidate."""
        candidate_dir = self._paths.base_dir / "insights" / tenant_id / "kb_candidates"
        candidate_dir.mkdir(parents=True, exist_ok=True)
        return candidate_dir / f"{ticket_id}.json"

    def save(self, candidate: KBCandidate) -> None:
        """Save a KB candidate to disk."""
        path = self._candidate_path(candidate.tenant_id, candidate.ticket_id)
        data = candidate.model_dump(mode="json")

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info(
            "Saved KB candidate %s for tenant %s",
            candidate.ticket_id,
            candidate.tenant_id,
        )

    def get(self, tenant_id: str, ticket_id: str) -> KBCandidate | None:
        """Retrieve a KB candidate by ticket ID."""
        path = self._candidate_path(tenant_id, ticket_id)
        if not path.exists():
            return None

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return KBCandidate.model_validate(data)

    def list_candidates(
        self, tenant_id: str, status: str | None = None
    ) -> list[KBCandidate]:
        """List all KB candidates for a tenant, optionally filtered by status."""
        candidate_dir = self._paths.base_dir / "insights" / tenant_id / "kb_candidates"
        if not candidate_dir.exists():
            return []

        candidates = []
        for path in candidate_dir.glob("*.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                candidate = KBCandidate.model_validate(data)

                if status is None or candidate.status == status:
                    candidates.append(candidate)
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning("Failed to load candidate %s: %s", path, e)

        # Sort by created_at descending
        candidates.sort(key=lambda c: c.created_at, reverse=True)
        return candidates

    def promote(
        self,
        tenant_id: str,
        ticket_id: str,
        target_kb_id: str,
    ) -> KBCandidate | None:
        """Promote a candidate to approved status.

        Returns the updated candidate, or None if not found.
        """
        candidate = self.get(tenant_id, ticket_id)
        if candidate is None:
            return None

        if candidate.status != "pending_review":
            logger.warning(
                "Cannot promote candidate %s: status is %s",
                ticket_id,
                candidate.status,
            )
            return None

        # Update status to approved
        updated = candidate.model_copy(
            update={
                "status": "approved",
                "metadata_tags": {
                    **candidate.metadata_tags,
                    "target_kb_id": target_kb_id,
                    "approved_at": datetime.now(UTC).isoformat(),
                },
            }
        )

        self.save(updated)
        logger.info(
            "Promoted KB candidate %s to approved (target_kb=%s)",
            ticket_id,
            target_kb_id,
        )
        return updated

    def dismiss(
        self,
        tenant_id: str,
        ticket_id: str,
        reason: str,
    ) -> KBCandidate | None:
        """Dismiss a candidate with a reason.

        Returns the updated candidate, or None if not found.
        """
        candidate = self.get(tenant_id, ticket_id)
        if candidate is None:
            return None

        if candidate.status not in ("pending_review", "approved"):
            logger.warning(
                "Cannot dismiss candidate %s: status is %s",
                ticket_id,
                candidate.status,
            )
            return None

        # Update status to dismissed
        updated = candidate.model_copy(
            update={
                "status": "dismissed",
                "dismiss_reason": reason,
            }
        )

        self.save(updated)
        logger.info(
            "Dismissed KB candidate %s: %s",
            ticket_id,
            reason,
        )
        return updated

    def delete(self, tenant_id: str, ticket_id: str) -> bool:
        """Delete a candidate file.

        Returns True if deleted, False if not found.
        """
        path = self._candidate_path(tenant_id, ticket_id)
        if not path.exists():
            return False

        path.unlink()
        logger.info("Deleted KB candidate %s for tenant %s", ticket_id, tenant_id)
        return True
