"""Base classes for canvas component executors."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from deerflow.canvas.models import CanvasNode, NodeResult


@dataclass
class ExecutionContext:
    """Context passed to component executors during execution."""

    canvas_id: str
    thread_id: str
    db_connections: dict[str, Any]  # connection_id -> connection info
    sandbox: Any  # Sandbox instance for Python execution
    resolved_variables: dict[str, Any] = field(default_factory=dict)


class ComponentExecutor(ABC):
    """Abstract base class for canvas component executors."""

    @property
    @abstractmethod
    def node_type(self) -> str:
        """Return the node type this executor handles."""
        pass

    @abstractmethod
    async def execute(
        self,
        node: CanvasNode,
        context: ExecutionContext,
    ) -> NodeResult:
        """Execute the node and return the result.

        Args:
            node: The node to execute
            context: Execution context with connections and variables

        Returns:
            NodeResult with execution outcome
        """
        pass

    def validate(self, node: CanvasNode) -> list[str]:
        """Validate node configuration.

        Args:
            node: The node to validate

        Returns:
            List of validation error messages, empty if valid
        """
        return []
