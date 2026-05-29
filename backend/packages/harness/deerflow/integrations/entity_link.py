"""Entity link resolver for cross-system ID mapping."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deerflow.integrations.config import EntityLinkConfig

from deerflow.integrations.errors import EntityLinkNotFound


class EntityLinkResolver:
    """Resolves canonical IDs to system-specific remote IDs."""

    def __init__(self, entity_links: list[EntityLinkConfig]) -> None:
        """Initialize resolver with entity links.

        Args:
            entity_links: List of entity link configurations
        """
        self._links = entity_links
        self._build_index()

    def _build_index(self) -> None:
        """Build lookup indexes for fast resolution."""
        # canonical_id -> entity_link
        self._by_canonical: dict[str, EntityLinkConfig] = {}
        # (entity_type, system_key, remote_id) -> entity_link
        self._by_remote: dict[tuple[str, str, str], EntityLinkConfig] = {}

        for link in self._links:
            if link.status != "active":
                continue
            self._by_canonical[link.canonical_id] = link
            for entry in link.links:
                key = (link.entity_type, entry.system_key, entry.remote_id)
                self._by_remote[key] = link

    def resolve(
        self,
        canonical_id: str,
        system_key: str,
        min_confidence: float = 0.0,
    ) -> str:
        """Resolve canonical_id to remote_id for a specific system.

        Args:
            canonical_id: Platform-level unified ID
            system_key: Target system identifier
            min_confidence: Minimum mapping confidence required

        Returns:
            Remote ID in the target system

        Raises:
            EntityLinkNotFound: If no mapping exists or confidence too low
        """
        link = self._by_canonical.get(canonical_id)
        if link is None:
            raise EntityLinkNotFound(
                message=f"No entity link for canonical_id={canonical_id}",
                system_key=system_key,
            )

        for entry in link.links:
            if entry.system_key != system_key:
                continue
            if entry.confidence < min_confidence:
                raise EntityLinkNotFound(
                    message=f"Confidence {entry.confidence} below threshold {min_confidence}",
                    system_key=system_key,
                )
            return entry.remote_id

        raise EntityLinkNotFound(
            message=f"No mapping for canonical_id={canonical_id} in system {system_key}",
            system_key=system_key,
        )

    def resolve_by_remote(
        self,
        entity_type: str,
        system_key: str,
        remote_id: str,
        min_confidence: float = 0.0,
    ) -> str:
        """Resolve remote_id to canonical_id.

        Args:
            entity_type: Entity type (e.g., 'asset', 'measurement_point')
            system_key: Source system identifier
            remote_id: ID in the source system
            min_confidence: Minimum mapping confidence required

        Returns:
            Canonical ID

        Raises:
            EntityLinkNotFound: If no mapping exists or confidence too low
        """
        key = (entity_type, system_key, remote_id)
        link = self._by_remote.get(key)

        if link is None:
            raise EntityLinkNotFound(
                message=f"No mapping for {entity_type}:{remote_id}",
                system_key=system_key,
            )

        for entry in link.links:
            if entry.system_key == system_key and entry.remote_id == remote_id:
                if entry.confidence < min_confidence:
                    raise EntityLinkNotFound(
                        message=f"Confidence {entry.confidence} below threshold {min_confidence}",
                        system_key=system_key,
                    )
                return link.canonical_id

        raise EntityLinkNotFound(
            message=f"No mapping for {entity_type}:{remote_id}",
            system_key=system_key,
        )

    def get_all_links(self, canonical_id: str) -> list[tuple[str, str, float]]:
        """Get all system mappings for a canonical_id.

        Args:
            canonical_id: Platform-level unified ID

        Returns:
            List of (system_key, remote_id, confidence) tuples
        """
        link = self._by_canonical.get(canonical_id)
        if link is None:
            return []

        return [
            (entry.system_key, entry.remote_id, entry.confidence)
            for entry in link.links
        ]
