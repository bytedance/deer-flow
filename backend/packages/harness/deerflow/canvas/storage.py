"""Canvas storage - persist canvas data to files."""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from deerflow.canvas.models import Canvas

logger = logging.getLogger(__name__)


class CanvasStorage:
    """Manages canvas persistence to JSON files.

    Canvas files are stored at:
        {base_dir}/threads/{thread_id}/canvas/canvas.json
    """

    def __init__(self, base_dir: Path | None = None):
        """Initialize storage.

        Args:
            base_dir: Base directory for canvas files.
                     Defaults to .deer-flow in backend directory.
        """
        if base_dir is None:
            from deerflow.config.paths import get_paths

            base_dir = get_paths().base_dir

        self.base_dir = Path(base_dir)

    def _canvas_path(self, thread_id: str) -> Path:
        """Get path to canvas file for thread.

        Args:
            thread_id: Thread ID to get canvas path for

        Returns:
            Path to canvas.json file

        Raises:
            ValueError: If thread_id contains path traversal characters
        """
        # Prevent path traversal attacks
        if ".." in thread_id or "/" in thread_id or "\\" in thread_id:
            raise ValueError(f"Invalid thread_id: {thread_id}")
        canvas_path = self.base_dir / "threads" / thread_id / "canvas" / "canvas.json"
        # Double-check: ensure resolved path is still within base_dir
        try:
            canvas_path.resolve().relative_to(self.base_dir.resolve())
        except ValueError:
            raise ValueError(f"Path traversal detected in thread_id: {thread_id}")
        return canvas_path

    def save(self, canvas: Canvas) -> None:
        """Save canvas to file.

        Args:
            canvas: Canvas to save
        """
        canvas_path = self._canvas_path(canvas.thread_id)
        canvas_path.parent.mkdir(parents=True, exist_ok=True)

        # Update timestamp
        canvas.updated_at = datetime.now(UTC)

        # Write JSON
        canvas_json = canvas.model_dump(mode="json")
        canvas_path.write_text(json.dumps(canvas_json, indent=2, default=str))

        logger.info(f"Saved canvas {canvas.id} for thread {canvas.thread_id}")

    def load(self, thread_id: str) -> Canvas | None:
        """Load canvas for thread.

        Args:
            thread_id: Thread ID to load canvas for

        Returns:
            Canvas if exists, None otherwise
        """
        canvas_path = self._canvas_path(thread_id)

        if not canvas_path.exists():
            return None

        try:
            canvas_json = json.loads(canvas_path.read_text())
            return Canvas(**canvas_json)
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Failed to load canvas for thread {thread_id}: {e}")
            return None

    def delete(self, thread_id: str) -> None:
        """Delete canvas for thread.

        Args:
            thread_id: Thread ID to delete canvas for
        """
        canvas_path = self._canvas_path(thread_id)

        if canvas_path.exists():
            canvas_path.unlink()
            # Remove empty directories
            try:
                canvas_path.parent.rmdir()
                canvas_path.parent.parent.rmdir()
            except OSError:
                pass  # Directory not empty

            logger.info(f"Deleted canvas for thread {thread_id}")

    def exists(self, thread_id: str) -> bool:
        """Check if canvas exists for thread.

        Args:
            thread_id: Thread ID to check

        Returns:
            True if canvas exists
        """
        return self._canvas_path(thread_id).exists()
