"""Closure-to-knowledge pipeline.

Extracts resolution data from closure ticket audit event payloads and
generates knowledge base candidates with a human review gate.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from deerflow.insights.models import KBCandidate
from deerflow.persistence.models.closure_ticket import ClosureTicketEventRow

logger = logging.getLogger(__name__)


class ClosureKnowledgeExtractor:
    """Extract KB candidates from closed tickets on verify_close transition."""

    async def extract(
        self,
        *,
        ticket_id: str,
        tenant_id: str,
        events: list[ClosureTicketEventRow],
    ) -> KBCandidate | None:
        """Extract a KB candidate from ticket events.

        Looks for verification_summary and evidence in submit_verification
        and verify_close event payloads. Combines with ticket metadata.

        Args:
            ticket_id: The closure ticket ID
            tenant_id: Tenant identifier
            events: List of audit events for this ticket

        Returns:
            KBCandidate if extraction succeeded, None otherwise
        """
        # Find submit_verification and verify_close events
        submit_event = None
        verify_event = None

        for event in events:
            if event.action == "submit_verification":
                submit_event = event
            elif event.action == "verify_close":
                verify_event = event

        # Need at least one verification event
        if not submit_event and not verify_event:
            logger.debug(
                "No verification events found for ticket %s, skipping KB extraction",
                ticket_id,
            )
            return None

        # Extract verification_summary and evidence from payloads
        verification_summaries = []
        evidence_items = []

        if submit_event and submit_event.payload:
            summary = submit_event.payload.get("verification_summary")
            if summary:
                verification_summaries.append(summary)
            evidence = submit_event.payload.get("evidence")
            if isinstance(evidence, list):
                evidence_items.extend(evidence)

        if verify_event and verify_event.payload:
            summary = verify_event.payload.get("verification_summary")
            if summary:
                verification_summaries.append(summary)

        # Build document body from verification summaries
        body_parts = []
        if verification_summaries:
            body_parts.append("## Verification Summary\n\n")
            for summary in verification_summaries:
                body_parts.append(f"- {summary}\n")

        if evidence_items:
            body_parts.append("\n## Evidence\n\n")
            for item in evidence_items:
                body_parts.append(f"- {item}\n")

        body = "".join(body_parts)

        if not body.strip():
            logger.debug(
                "No verification content extracted for ticket %s, skipping",
                ticket_id,
            )
            return None

        # Build metadata tags
        metadata_tags: dict[str, Any] = {
            "source_ticket_id": ticket_id,
            "source_type": "closure_resolution",
        }

        if verify_event:
            metadata_tags["verifier_id"] = verify_event.actor_id
            metadata_tags["closed_at"] = verify_event.created_at.isoformat()

        # Create candidate
        candidate = KBCandidate(
            ticket_id=ticket_id,
            tenant_id=tenant_id,
            title=f"Resolution: Ticket {ticket_id}",
            body=body,
            metadata_tags=metadata_tags,
            status="pending_review",
            created_at=datetime.now(UTC),
        )

        logger.info(
            "Extracted KB candidate from ticket %s: %d chars",
            ticket_id,
            len(body),
        )
        return candidate
