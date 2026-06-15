"""Blueprint repository — in-memory cache of blueprints derived from builtin templates.

Blueprints are generated once at startup from the 8 builtin report templates.
They are read-only — users create new templates *from* blueprints, they don't
modify blueprints themselves.

Layout:
    In-memory dict: blueprint_id → BlueprintDefinition
    (Future: could persist to {DEER_FLOW_HOME}/blueprints/ for custom blueprints)
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from deerflow.report_templates.blueprint_generator import generate_all_blueprints
from deerflow.report_templates.blueprint_schema import BlueprintDefinition

logger = logging.getLogger(__name__)


class BlueprintNotFoundError(Exception):
    def __init__(self, blueprint_id: str) -> None:
        super().__init__(f"blueprint {blueprint_id!r} not found")
        self.blueprint_id = blueprint_id


class BlueprintRepositoryError(Exception):
    pass


@dataclass
class BlueprintRepository:
    """In-memory blueprint cache, populated once at startup."""

    _blueprints: dict[str, BlueprintDefinition]
    _lock: threading.RLock

    @classmethod
    def initialize(cls) -> BlueprintRepository:
        """Generate blueprints from all builtin templates and cache them."""
        repo = cls(_blueprints={}, _lock=threading.RLock())
        repo._refresh()
        return repo

    def _refresh(self) -> None:
        """Regenerate all blueprints from builtin templates."""
        try:
            blueprints = generate_all_blueprints()
        except Exception as e:
            logger.error(f"Failed to generate blueprints: {e}")
            raise BlueprintRepositoryError(f"blueprint generation failed: {e}") from e

        with self._lock:
            self._blueprints = {bp.id: bp for bp in blueprints}
        logger.info(f"Loaded {len(self._blueprints)} blueprints")

    def list_blueprints(
        self,
        category: str | None = None,
    ) -> list[BlueprintDefinition]:
        """Return all blueprints, optionally filtered by category."""
        with self._lock:
            items = list(self._blueprints.values())

        if category:
            items = [bp for bp in items if bp.category == category]

        items.sort(key=lambda bp: bp.id)
        return items

    def get_blueprint(self, blueprint_id: str) -> BlueprintDefinition:
        """Get a single blueprint by ID."""
        with self._lock:
            bp = self._blueprints.get(blueprint_id)
        if bp is None:
            raise BlueprintNotFoundError(blueprint_id)
        return bp

    def blueprint_exists(self, blueprint_id: str) -> bool:
        with self._lock:
            return blueprint_id in self._blueprints

    def count(self) -> int:
        with self._lock:
            return len(self._blueprints)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_repo: BlueprintRepository | None = None
_repo_lock = threading.Lock()


def get_blueprint_repository() -> BlueprintRepository:
    """Get or create the global blueprint repository singleton."""
    global _repo
    if _repo is None:
        with _repo_lock:
            if _repo is None:
                _repo = BlueprintRepository.initialize()
    return _repo
