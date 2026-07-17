"""Regression tests for the LOW-severity bug bash batch (2026-07-12).

Covers the unit-testable fixes shipped in PR ``fix/low-batch-deerflow``:

- ``PortAllocator.allocate`` argument validation.
- ``resolve_host_addresses`` ignores non-INET address families.
- ``LocalSandbox.__init__`` keeps accepting the historical ``id=`` keyword
  (the bug-bash rename was dropped in review as an API break).
- ``FileMemoryStorage.load`` is safe under concurrent first-time loads.
- ``LocalSkillStorage.ainstall_skill_from_archive`` raises
  ``FileNotFoundError`` for missing/non-file paths before scanning.
"""

from __future__ import annotations

import socket
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core.storage import FileMemoryStorage
from deerflow.community.url_safety import resolve_host_addresses
from deerflow.sandbox.local.local_sandbox import LocalSandbox
from deerflow.skills.storage.local_skill_storage import LocalSkillStorage
from deerflow.utils.network import PortAllocator

# ---------------------------------------------------------------------------
# PortAllocator validation (utils/network.py)
# ---------------------------------------------------------------------------


class TestPortAllocatorValidation:
    """``allocate`` must reject obviously invalid arguments up front."""

    def test_rejects_zero_start_port(self):
        with pytest.raises(ValueError, match="start_port"):
            PortAllocator().allocate(start_port=0)

    def test_rejects_negative_start_port(self):
        with pytest.raises(ValueError, match="start_port"):
            PortAllocator().allocate(start_port=-1)

    def test_rejects_out_of_range_start_port(self):
        with pytest.raises(ValueError, match="start_port"):
            PortAllocator().allocate(start_port=65536)

    def test_rejects_zero_max_range(self):
        with pytest.raises(ValueError, match="max_range"):
            PortAllocator().allocate(start_port=8080, max_range=0)

    def test_rejects_negative_max_range(self):
        with pytest.raises(ValueError, match="max_range"):
            PortAllocator().allocate(start_port=8080, max_range=-5)

    def test_rejects_non_int_start_port(self):
        with pytest.raises(ValueError, match="start_port"):
            PortAllocator().allocate(start_port="8080")  # type: ignore[arg-type]

    def test_allocation_still_succeeds_for_valid_args(self):
        # Use a high start port unlikely to collide with anything in CI.
        allocator = PortAllocator()
        port = allocator.allocate(start_port=50000, max_range=10)
        assert 50000 <= port < 50010
        allocator.release(port)


# ---------------------------------------------------------------------------
# url_safety.resolve_host_addresses (community/url_safety.py)
# ---------------------------------------------------------------------------


class TestResolveHostAddressesFamilyFilter:
    """Only AF_INET / AF_INET6 entries should reach ``ip_address``."""

    def test_skips_non_inet_address_families(self):
        # Inject a fake getaddrinfo result that mixes INET with a non-INET
        # family. Without the family filter the non-INET entry would raise
        # ``ValueError`` from ``ip_address`` and the bare ``except`` would
        # silently drop it; with the filter the entry is rejected upfront.
        # Use a literal int (999) instead of ``socket.AF_APPLETALK`` which is
        # not defined on Windows.  Any non-INET/non-INET6 address family value
        # works — the value only needs to be a valid integer that isn't INET or
        # INET6 for the family filter to reject it.
        fake_infos = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.0.0.1", 0)),
            (999, socket.SOCK_STREAM, 0, "", (b"\x00\x00\x00\x00",)),
            (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("::1", 0, 0, 0)),
        ]
        with patch("deerflow.community.url_safety.socket.getaddrinfo", return_value=fake_infos):
            addrs = resolve_host_addresses("example.com")
        assert [str(a) for a in addrs] == ["10.0.0.1", "::1"]


# ---------------------------------------------------------------------------
# LocalSandbox constructor compatibility (sandbox/local/local_sandbox.py)
# ---------------------------------------------------------------------------


class TestLocalSandboxConstructorCompatibility:
    """``LocalSandbox`` must keep accepting the historical ``id=`` keyword.

    The 2026-07 bug bash proposed renaming the ``id`` parameter to
    ``sandbox_id`` to stop shadowing the built-in, but the rename was dropped
    in review: external consumers of the published harness construct
    ``LocalSandbox(id="...")``, so removing the keyword is an API break.
    These tests pin the public constructor shape.
    """

    def test_positional_id(self):
        sb = LocalSandbox("local:user:thread:42")
        assert sb.id == "local:user:thread:42"

    def test_keyword_id(self):
        sb = LocalSandbox(id="local:user:thread:42")
        assert sb.id == "local:user:thread:42"


# ---------------------------------------------------------------------------
# FileMemoryStorage.load race (agents/memory/backends/deermem/deermem/core/storage.py)
# ---------------------------------------------------------------------------


class TestFileMemoryStorageLoadConcurrency:
    """Concurrent cold-cache loads must not race past the cache_lock."""

    def test_concurrent_cold_loads_share_one_disk_read(self, tmp_path: Path):
        # Force a known path that lives under tmp_path so we do not depend on
        # the global config resolution.
        target = tmp_path / "mem.json"

        storage = FileMemoryStorage(DeerMemConfig(storage_path=str(tmp_path)))

        read_count = 0
        read_lock = threading.Lock()

        real_reader = storage._read_document

        def counting_reader(path, agent_name, *, user_id=None):
            nonlocal read_count
            with read_lock:
                read_count += 1
            return real_reader(path, agent_name, user_id=user_id)

        # Patch the cache key + file path lookup to drive every call at the
        # same (user_id, agent_name) tuple and the same file, and pin the
        # scope signature so every thread sees the same cache key state.
        with (
            patch.object(storage, "_get_memory_file_path", return_value=target),
            patch.object(storage, "_cache_key", return_value=("u", "a")),
            patch.object(storage, "_legacy_agent_memory_path", return_value=None),
            patch.object(storage, "_global_json_needs_migration", return_value=False),
            patch.object(storage, "_scope_signature", return_value=("sig",)),
            patch.object(storage, "_read_document", side_effect=counting_reader),
        ):
            barrier = threading.Barrier(8)

            def worker():
                barrier.wait()
                data = storage.load("a", user_id="u")
                assert data["version"] == "1.0"

            threads = [threading.Thread(target=worker) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        # All 8 threads raced past the barrier; the single critical section
        # should have produced exactly one disk read. The original code's
        # signature-outside-lock + read-outside-lock shape would race and
        # could hit the disk multiple times.
        assert read_count == 1, f"expected one disk read, got {read_count}"


# ---------------------------------------------------------------------------
# LocalSkillStorage.ainstall_skill_from_archive (skills/storage/local_skill_storage.py)
# ---------------------------------------------------------------------------


class TestAinstallSkillFromArchivePreflight:
    """Missing or non-file archive paths must fail fast with ``FileNotFoundError``."""

    def test_missing_path_raises_file_not_found(self, tmp_path: Path):
        storage = LocalSkillStorage(host_path=str(tmp_path))
        missing = tmp_path / "does-not-exist.zip"
        with pytest.raises(FileNotFoundError, match="Skill archive not found"):
            # ``ainstall_skill_from_archive`` is async; drive it via asyncio.run.
            import asyncio

            asyncio.run(storage.ainstall_skill_from_archive(missing))

    def test_directory_path_raises_file_not_found(self, tmp_path: Path):
        storage = LocalSkillStorage(host_path=str(tmp_path))
        # ``is_file()`` returns False for directories, so this is the other
        # branch of the preflight check.
        with pytest.raises(FileNotFoundError, match="Skill archive not found"):
            import asyncio

            asyncio.run(storage.ainstall_skill_from_archive(tmp_path))
