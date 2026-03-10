"""Tests for channel file attachment support (ResolvedAttachment, resolution, send_file)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.channels.base import Channel
from src.channels.message_bus import MessageBus, OutboundMessage, ResolvedAttachment


def _run(coro):
    """Run an async coroutine synchronously."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# ResolvedAttachment tests
# ---------------------------------------------------------------------------


class TestResolvedAttachment:
    def test_basic_construction(self, tmp_path):
        f = tmp_path / "test.pdf"
        f.write_bytes(b"PDF content")

        att = ResolvedAttachment(
            virtual_path="/mnt/user-data/outputs/test.pdf",
            actual_path=f,
            filename="test.pdf",
            mime_type="application/pdf",
            size=11,
            is_image=False,
        )
        assert att.filename == "test.pdf"
        assert att.is_image is False
        assert att.size == 11

    def test_image_detection(self, tmp_path):
        f = tmp_path / "photo.png"
        f.write_bytes(b"\x89PNG")

        att = ResolvedAttachment(
            virtual_path="/mnt/user-data/outputs/photo.png",
            actual_path=f,
            filename="photo.png",
            mime_type="image/png",
            size=4,
            is_image=True,
        )
        assert att.is_image is True


# ---------------------------------------------------------------------------
# OutboundMessage.attachments field tests
# ---------------------------------------------------------------------------


class TestOutboundMessageAttachments:
    def test_default_empty_attachments(self):
        msg = OutboundMessage(
            channel_name="test",
            chat_id="c1",
            thread_id="t1",
            text="hello",
        )
        assert msg.attachments == []

    def test_attachments_populated(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("content")

        att = ResolvedAttachment(
            virtual_path="/mnt/user-data/outputs/file.txt",
            actual_path=f,
            filename="file.txt",
            mime_type="text/plain",
            size=7,
            is_image=False,
        )
        msg = OutboundMessage(
            channel_name="test",
            chat_id="c1",
            thread_id="t1",
            text="hello",
            attachments=[att],
        )
        assert len(msg.attachments) == 1
        assert msg.attachments[0].filename == "file.txt"


# ---------------------------------------------------------------------------
# _resolve_attachments tests
# ---------------------------------------------------------------------------


class TestResolveAttachments:
    def test_resolves_existing_file(self, tmp_path):
        """Successfully resolves a virtual path to an existing file."""
        from src.channels.manager import _resolve_attachments

        # Create the directory structure: threads/{thread_id}/user-data/outputs/
        thread_id = "test-thread-123"
        outputs_dir = tmp_path / "threads" / thread_id / "user-data" / "outputs"
        outputs_dir.mkdir(parents=True)
        test_file = outputs_dir / "report.pdf"
        test_file.write_bytes(b"%PDF-1.4 fake content")

        mock_paths = MagicMock()
        mock_paths.resolve_virtual_path.return_value = test_file
        mock_paths.sandbox_outputs_dir.return_value = outputs_dir

        with patch("src.config.paths.get_paths", return_value=mock_paths):
            result = _resolve_attachments(thread_id, ["/mnt/user-data/outputs/report.pdf"])

        assert len(result) == 1
        assert result[0].filename == "report.pdf"
        assert result[0].mime_type == "application/pdf"
        assert result[0].is_image is False
        assert result[0].size == len(b"%PDF-1.4 fake content")

    def test_resolves_image_file(self, tmp_path):
        """Images are detected by MIME type."""
        from src.channels.manager import _resolve_attachments

        thread_id = "test-thread"
        outputs_dir = tmp_path / "threads" / thread_id / "user-data" / "outputs"
        outputs_dir.mkdir(parents=True)
        img = outputs_dir / "chart.png"
        img.write_bytes(b"\x89PNG fake image")

        mock_paths = MagicMock()
        mock_paths.resolve_virtual_path.return_value = img
        mock_paths.sandbox_outputs_dir.return_value = outputs_dir

        with patch("src.config.paths.get_paths", return_value=mock_paths):
            result = _resolve_attachments(thread_id, ["/mnt/user-data/outputs/chart.png"])

        assert len(result) == 1
        assert result[0].is_image is True
        assert result[0].mime_type == "image/png"

    def test_skips_missing_file(self, tmp_path):
        """Missing files are skipped with a warning."""
        from src.channels.manager import _resolve_attachments

        outputs_dir = tmp_path / "outputs"
        outputs_dir.mkdir()

        mock_paths = MagicMock()
        mock_paths.resolve_virtual_path.return_value = outputs_dir / "nonexistent.txt"
        mock_paths.sandbox_outputs_dir.return_value = outputs_dir

        with patch("src.config.paths.get_paths", return_value=mock_paths):
            result = _resolve_attachments("t1", ["/mnt/user-data/outputs/nonexistent.txt"])

        assert result == []

    def test_skips_invalid_path(self):
        """Invalid paths (ValueError from resolve) are skipped."""
        from src.channels.manager import _resolve_attachments

        mock_paths = MagicMock()
        mock_paths.resolve_virtual_path.side_effect = ValueError("bad path")

        with patch("src.config.paths.get_paths", return_value=mock_paths):
            result = _resolve_attachments("t1", ["/invalid/path"])

        assert result == []

    def test_rejects_uploads_path(self):
        """Paths under /mnt/user-data/uploads/ are rejected (security)."""
        from src.channels.manager import _resolve_attachments

        mock_paths = MagicMock()

        with patch("src.config.paths.get_paths", return_value=mock_paths):
            result = _resolve_attachments("t1", ["/mnt/user-data/uploads/secret.pdf"])

        assert result == []
        mock_paths.resolve_virtual_path.assert_not_called()

    def test_rejects_workspace_path(self):
        """Paths under /mnt/user-data/workspace/ are rejected (security)."""
        from src.channels.manager import _resolve_attachments

        mock_paths = MagicMock()

        with patch("src.config.paths.get_paths", return_value=mock_paths):
            result = _resolve_attachments("t1", ["/mnt/user-data/workspace/config.py"])

        assert result == []
        mock_paths.resolve_virtual_path.assert_not_called()

    def test_rejects_path_traversal_escape(self, tmp_path):
        """Paths that escape the outputs directory after resolution are rejected."""
        from src.channels.manager import _resolve_attachments

        thread_id = "t1"
        outputs_dir = tmp_path / "threads" / thread_id / "user-data" / "outputs"
        outputs_dir.mkdir(parents=True)
        # Simulate a resolved path that escapes outside the outputs directory
        escaped_file = tmp_path / "threads" / thread_id / "user-data" / "uploads" / "stolen.txt"
        escaped_file.parent.mkdir(parents=True, exist_ok=True)
        escaped_file.write_text("sensitive")

        mock_paths = MagicMock()
        mock_paths.resolve_virtual_path.return_value = escaped_file
        mock_paths.sandbox_outputs_dir.return_value = outputs_dir

        with patch("src.config.paths.get_paths", return_value=mock_paths):
            result = _resolve_attachments(thread_id, ["/mnt/user-data/outputs/../uploads/stolen.txt"])

        assert result == []

    def test_multiple_artifacts_partial_resolution(self, tmp_path):
        """Mixed valid/invalid artifacts: only valid ones are returned."""
        from src.channels.manager import _resolve_attachments

        thread_id = "t1"
        outputs_dir = tmp_path / "outputs"
        outputs_dir.mkdir()
        good_file = outputs_dir / "data.csv"
        good_file.write_text("a,b,c")

        mock_paths = MagicMock()
        mock_paths.sandbox_outputs_dir.return_value = outputs_dir

        def resolve_side_effect(tid, vpath):
            if "data.csv" in vpath:
                return good_file
            return tmp_path / "missing.txt"

        mock_paths.resolve_virtual_path.side_effect = resolve_side_effect

        with patch("src.config.paths.get_paths", return_value=mock_paths):
            result = _resolve_attachments(
                thread_id,
                ["/mnt/user-data/outputs/data.csv", "/mnt/user-data/outputs/missing.txt"],
            )

        assert len(result) == 1
        assert result[0].filename == "data.csv"


# ---------------------------------------------------------------------------
# Channel base class _on_outbound with attachments
# ---------------------------------------------------------------------------


class _DummyChannel(Channel):
    """Concrete channel for testing the base class behavior."""

    def __init__(self, bus):
        super().__init__(name="dummy", bus=bus, config={})
        self.sent_messages: list[OutboundMessage] = []
        self.sent_files: list[tuple[OutboundMessage, ResolvedAttachment]] = []

    async def start(self):
        pass

    async def stop(self):
        pass

    async def send(self, msg: OutboundMessage) -> None:
        self.sent_messages.append(msg)

    async def send_file(self, msg: OutboundMessage, attachment: ResolvedAttachment) -> bool:
        self.sent_files.append((msg, attachment))
        return True


class TestBaseChannelOnOutbound:
    def test_send_file_called_for_each_attachment(self, tmp_path):
        """_on_outbound sends text first, then uploads each attachment."""
        bus = MessageBus()
        ch = _DummyChannel(bus)

        f1 = tmp_path / "a.txt"
        f1.write_text("aaa")
        f2 = tmp_path / "b.png"
        f2.write_bytes(b"\x89PNG")

        att1 = ResolvedAttachment("/mnt/user-data/outputs/a.txt", f1, "a.txt", "text/plain", 3, False)
        att2 = ResolvedAttachment("/mnt/user-data/outputs/b.png", f2, "b.png", "image/png", 4, True)

        msg = OutboundMessage(
            channel_name="dummy",
            chat_id="c1",
            thread_id="t1",
            text="Here are your files",
            attachments=[att1, att2],
        )

        _run(ch._on_outbound(msg))

        assert len(ch.sent_messages) == 1
        assert len(ch.sent_files) == 2
        assert ch.sent_files[0][1].filename == "a.txt"
        assert ch.sent_files[1][1].filename == "b.png"

    def test_no_attachments_no_send_file(self):
        """When there are no attachments, send_file is not called."""
        bus = MessageBus()
        ch = _DummyChannel(bus)

        msg = OutboundMessage(
            channel_name="dummy",
            chat_id="c1",
            thread_id="t1",
            text="No files here",
        )

        _run(ch._on_outbound(msg))

        assert len(ch.sent_messages) == 1
        assert len(ch.sent_files) == 0

    def test_send_file_failure_does_not_block_others(self, tmp_path):
        """If one attachment upload fails, remaining attachments still get sent."""
        bus = MessageBus()
        ch = _DummyChannel(bus)

        # Override send_file to fail on first call, succeed on second
        call_count = 0
        original_send_file = ch.send_file

        async def flaky_send_file(msg, att):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("upload failed")
            return await original_send_file(msg, att)

        ch.send_file = flaky_send_file  # type: ignore

        f1 = tmp_path / "fail.txt"
        f1.write_text("x")
        f2 = tmp_path / "ok.txt"
        f2.write_text("y")

        att1 = ResolvedAttachment("/mnt/user-data/outputs/fail.txt", f1, "fail.txt", "text/plain", 1, False)
        att2 = ResolvedAttachment("/mnt/user-data/outputs/ok.txt", f2, "ok.txt", "text/plain", 1, False)

        msg = OutboundMessage(
            channel_name="dummy",
            chat_id="c1",
            thread_id="t1",
            text="files",
            attachments=[att1, att2],
        )

        _run(ch._on_outbound(msg))

        # First upload failed, second succeeded
        assert len(ch.sent_files) == 1
        assert ch.sent_files[0][1].filename == "ok.txt"

    def test_send_raises_skips_file_uploads(self, tmp_path):
        """When send() raises, file uploads are skipped entirely."""
        bus = MessageBus()
        ch = _DummyChannel(bus)

        async def failing_send(msg):
            raise RuntimeError("network error")

        ch.send = failing_send  # type: ignore

        f = tmp_path / "a.pdf"
        f.write_bytes(b"%PDF")
        att = ResolvedAttachment("/mnt/user-data/outputs/a.pdf", f, "a.pdf", "application/pdf", 4, False)
        msg = OutboundMessage(
            channel_name="dummy",
            chat_id="c1",
            thread_id="t1",
            text="Here is the file",
            attachments=[att],
        )

        _run(ch._on_outbound(msg))

        # send() raised, so send_file should never be called
        assert len(ch.sent_files) == 0

    def test_default_send_file_returns_false(self):
        """The base Channel.send_file returns False by default."""

        class MinimalChannel(Channel):
            async def start(self):
                pass

            async def stop(self):
                pass

            async def send(self, msg):
                pass

        bus = MessageBus()
        ch = MinimalChannel(name="minimal", bus=bus, config={})
        att = ResolvedAttachment("/x", Path("/x"), "x", "text/plain", 0, False)
        msg = OutboundMessage(channel_name="minimal", chat_id="c", thread_id="t", text="t")

        result = _run(ch.send_file(msg, att))
        assert result is False


# ---------------------------------------------------------------------------
# ChannelManager artifact resolution integration
# ---------------------------------------------------------------------------


class TestManagerArtifactResolution:
    def test_handle_chat_populates_attachments(self):
        """Verify _resolve_attachments is importable and works with the manager module."""
        from src.channels.manager import _resolve_attachments

        # Basic smoke test: empty artifacts returns empty list
        mock_paths = MagicMock()
        with patch("src.config.paths.get_paths", return_value=mock_paths):
            result = _resolve_attachments("t1", [])
        assert result == []

    def test_format_artifact_text_for_unresolved(self):
        """_format_artifact_text produces expected output."""
        from src.channels.manager import _format_artifact_text

        assert "report.pdf" in _format_artifact_text(["/mnt/user-data/outputs/report.pdf"])
        result = _format_artifact_text(["/mnt/user-data/outputs/a.txt", "/mnt/user-data/outputs/b.txt"])
        assert "a.txt" in result
        assert "b.txt" in result
