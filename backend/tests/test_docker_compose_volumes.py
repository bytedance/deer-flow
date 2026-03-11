"""Regression tests for Docker Compose volume mount configuration.

Validates that critical data directories are properly mounted in the
docker-compose-dev.yaml configuration to ensure data persistence
across container restarts.

Related issues:
- #1006: Conversation history lost after container restart
- #1066: Default checkpointer changed to SqliteSaver for persistence
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "docker" / "docker-compose-dev.yaml"


def _get_service_volumes(service_name: str) -> list[str]:
    """Parse docker-compose-dev.yaml and return volume mounts for a service."""
    content = COMPOSE_FILE.read_text()
    compose = yaml.safe_load(content)
    service = compose.get("services", {}).get(service_name, {})
    return service.get("volumes", [])


class TestLangGraphServiceVolumes:
    """Ensure the langgraph service mounts all directories needed for persistence."""

    def test_deer_flow_data_dir_is_mounted(self):
        """backend/.deer-flow must be mounted for checkpoints.db and memory.json."""
        volumes = _get_service_volumes("langgraph")
        mounted = any(".deer-flow" in v for v in volumes)
        assert mounted, (
            "The .deer-flow directory is not mounted in the langgraph service. "
            "This will cause checkpoints.db (conversation state) and memory.json "
            "to be lost on container restart."
        )

    def test_langgraph_api_dir_is_mounted(self):
        """backend/.langgraph_api must be mounted for thread metadata persistence.

        The LangGraph in-memory runtime stores thread metadata (thread list,
        titles, statuses, runs) in .langgraph_api/.langgraph_ops.pckl.
        Without this volume mount, all threads are lost on container restart.
        """
        volumes = _get_service_volumes("langgraph")
        mounted = any(".langgraph_api" in v for v in volumes)
        assert mounted, (
            "The .langgraph_api directory is not mounted in the langgraph service. "
            "This will cause thread metadata (thread list, titles, statuses) "
            "to be lost on container restart. "
            "Add '../backend/.langgraph_api:/app/backend/.langgraph_api' to volumes."
        )

    def test_src_dir_is_mounted(self):
        """backend/src must be mounted for hot-reload during development."""
        volumes = _get_service_volumes("langgraph")
        mounted = any("/src" in v for v in volumes)
        assert mounted, "backend/src should be mounted for hot-reload"

    def test_logs_dir_is_mounted(self):
        """logs directory must be mounted for log visibility on the host."""
        volumes = _get_service_volumes("langgraph")
        mounted = any("/logs" in v for v in volumes)
        assert mounted, "logs directory should be mounted"


class TestGatewayServiceVolumes:
    """Ensure the gateway service mounts necessary directories."""

    def test_deer_flow_data_dir_is_mounted(self):
        """backend/.deer-flow must be mounted in the gateway for memory access."""
        volumes = _get_service_volumes("gateway")
        mounted = any(".deer-flow" in v for v in volumes)
        assert mounted, (
            "The .deer-flow directory is not mounted in the gateway service."
        )
