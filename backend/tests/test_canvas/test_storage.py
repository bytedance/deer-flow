"""Tests for canvas storage."""

import json

from deerflow.canvas.models import AgentExecutionMode, Canvas, CanvasStatus
from deerflow.canvas.storage import CanvasStorage


class TestCanvasStorage:
    def test_create_storage(self, tmp_path):
        """CanvasStorage can be created with base directory."""
        storage = CanvasStorage(base_dir=tmp_path)
        assert storage.base_dir == tmp_path

    def test_save_canvas_creates_file(self, tmp_path):
        """Saving canvas creates JSON file."""
        storage = CanvasStorage(base_dir=tmp_path)

        canvas = Canvas(
            id="canvas-1",
            thread_id="thread-1",
            name="Test",
            description="Test canvas",
            agent_execution_mode=AgentExecutionMode.READONLY,
            nodes=[],
            edges=[],
            status=CanvasStatus.IDLE,
        )

        storage.save(canvas)

        # Check file exists
        canvas_file = tmp_path / "threads" / "thread-1" / "canvas" / "canvas.json"
        assert canvas_file.exists()

    def test_load_canvas_from_file(self, tmp_path):
        """Loading canvas reads JSON file."""
        storage = CanvasStorage(base_dir=tmp_path)

        # Create canvas file
        canvas_dir = tmp_path / "threads" / "thread-1" / "canvas"
        canvas_dir.mkdir(parents=True)
        canvas_file = canvas_dir / "canvas.json"

        canvas_data = {
            "id": "canvas-1",
            "thread_id": "thread-1",
            "name": "Loaded",
            "description": "Loaded canvas",
            "agent_execution_mode": "readonly",
            "nodes": [],
            "edges": [],
            "status": "idle",
            "execution_log": [],
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
        }
        canvas_file.write_text(json.dumps(canvas_data))

        canvas = storage.load("thread-1")

        assert canvas is not None
        assert canvas.id == "canvas-1"
        assert canvas.name == "Loaded"

    def test_load_returns_none_if_not_exists(self, tmp_path):
        """Loading non-existent canvas returns None."""
        storage = CanvasStorage(base_dir=tmp_path)

        canvas = storage.load("non-existent-thread")

        assert canvas is None

    def test_delete_canvas_removes_file(self, tmp_path):
        """Deleting canvas removes file."""
        storage = CanvasStorage(base_dir=tmp_path)

        canvas = Canvas(
            id="canvas-2",
            thread_id="thread-2",
            name="To Delete",
            description="Will be deleted",
            agent_execution_mode=AgentExecutionMode.READONLY,
            nodes=[],
            edges=[],
            status=CanvasStatus.IDLE,
        )

        storage.save(canvas)
        canvas_file = tmp_path / "threads" / "thread-2" / "canvas" / "canvas.json"
        assert canvas_file.exists()

        storage.delete("thread-2")

        assert not canvas_file.exists()

    def test_exists_returns_true_for_existing_canvas(self, tmp_path):
        """exists() returns True for saved canvas."""
        storage = CanvasStorage(base_dir=tmp_path)

        canvas = Canvas(
            id="canvas-3",
            thread_id="thread-3",
            name="Existing",
            description="",
            agent_execution_mode=AgentExecutionMode.READONLY,
            nodes=[],
            edges=[],
            status=CanvasStatus.IDLE,
        )

        storage.save(canvas)
        assert storage.exists("thread-3") is True
        assert storage.exists("non-existent") is False
