"""Tests for tenant-isolated memory storage."""

import json
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from deerflow.agents.memory.storage import FileMemoryStorage, create_empty_memory
from deerflow.config.memory_config import MemoryConfig
from deerflow.config.tenant import (
    _DEFAULT_TENANT_ID,
    get_current_tenant_id,
    reset_tenant_id,
    set_current_tenant_id,
)


class TestCacheKey:
    def test_default_tenant(self):
        assert FileMemoryStorage._cache_key() == (_DEFAULT_TENANT_ID, None)
        assert FileMemoryStorage._cache_key("my-agent") == (_DEFAULT_TENANT_ID, "my-agent")

    def test_named_tenant(self):
        token = set_current_tenant_id("acme")
        try:
            assert FileMemoryStorage._cache_key() == ("acme", None)
            assert FileMemoryStorage._cache_key("my-agent") == ("acme", "my-agent")
        finally:
            reset_tenant_id(token)


class TestTenantIsolation:
    def test_different_tenants_have_separate_cache_entries(self, tmp_path):
        memory_file_a = tmp_path / "tenant-a" / "memory.json"
        memory_file_a.parent.mkdir(parents=True)
        memory_file_a.write_text(json.dumps({"version": "1.0", "facts": [{"content": "fact-a"}]}))

        memory_file_b = tmp_path / "tenant-b" / "memory.json"
        memory_file_b.parent.mkdir(parents=True)
        memory_file_b.write_text(json.dumps({"version": "1.0", "facts": [{"content": "fact-b"}]}))

        storage = FileMemoryStorage()

        def mock_paths_for_tenant(tenant_dir):
            mock = MagicMock()
            mock.memory_file = tenant_dir / "memory.json"
            return mock

        with patch("deerflow.agents.memory.storage.get_paths") as mock_get_paths:
            with patch("deerflow.agents.memory.storage.get_memory_config", return_value=MemoryConfig(storage_path="")):
                mock_get_paths.side_effect = lambda: mock_paths_for_tenant(tmp_path / "tenant-a")
                token_a = set_current_tenant_id("tenant-a")
                try:
                    mem_a = storage.load()
                finally:
                    reset_tenant_id(token_a)

                mock_get_paths.side_effect = lambda: mock_paths_for_tenant(tmp_path / "tenant-b")
                token_b = set_current_tenant_id("tenant-b")
                try:
                    mem_b = storage.load()
                finally:
                    reset_tenant_id(token_b)

        assert mem_a["facts"][0]["content"] == "fact-a"
        assert mem_b["facts"][0]["content"] == "fact-b"

    def test_cache_does_not_leak_between_tenants(self, tmp_path):
        memory_file_a = tmp_path / "tenant-a" / "memory.json"
        memory_file_a.parent.mkdir(parents=True)
        memory_file_a.write_text(json.dumps({"version": "1.0", "facts": []}))
        memory_file_b = tmp_path / "tenant-b" / "memory.json"
        memory_file_b.parent.mkdir(parents=True)
        memory_file_b.write_text(json.dumps({"version": "1.0", "facts": []}))

        storage = FileMemoryStorage()

        with patch("deerflow.agents.memory.storage.get_memory_config", return_value=MemoryConfig(storage_path="")):
            with patch("deerflow.agents.memory.storage.get_paths") as mock_get_paths:
                mock_get_paths.return_value = MagicMock(memory_file=memory_file_a)
                token_a = set_current_tenant_id("tenant-a")
                try:
                    storage.load()
                finally:
                    reset_tenant_id(token_a)

                mock_get_paths.return_value = MagicMock(memory_file=memory_file_b)
                token_b = set_current_tenant_id("tenant-b")
                try:
                    storage.load()
                finally:
                    reset_tenant_id(token_b)

                assert ("tenant-a", None) in storage._memory_cache
                assert ("tenant-b", None) in storage._memory_cache
                assert storage._memory_cache[("tenant-a", None)] is not storage._memory_cache[("tenant-b", None)]

    def test_save_updates_correct_tenant_cache(self, tmp_path):
        memory_file_a = tmp_path / "tenant-a" / "memory.json"
        memory_file_a.parent.mkdir(parents=True)
        memory_file_b = tmp_path / "tenant-b" / "memory.json"
        memory_file_b.parent.mkdir(parents=True)

        storage = FileMemoryStorage()

        with patch("deerflow.agents.memory.storage.get_memory_config", return_value=MemoryConfig(storage_path="")):
            with patch("deerflow.agents.memory.storage.get_paths") as mock_get_paths:
                mock_get_paths.return_value = MagicMock(memory_file=memory_file_a)
                token_a = set_current_tenant_id("tenant-a")
                try:
                    storage.save({"version": "1.0", "facts": [{"content": "a"}]})
                finally:
                    reset_tenant_id(token_a)

                mock_get_paths.return_value = MagicMock(memory_file=memory_file_b)
                token_b = set_current_tenant_id("tenant-b")
                try:
                    storage.save({"version": "1.0", "facts": [{"content": "b"}]})
                finally:
                    reset_tenant_id(token_b)

            assert json.loads(memory_file_a.read_text())["facts"][0]["content"] == "a"
            assert json.loads(memory_file_b.read_text())["facts"][0]["content"] == "b"


class TestReloadTenantIsolation:
    def test_reload_only_invalidates_current_tenant(self, tmp_path):
        memory_file_a = tmp_path / "tenant-a" / "memory.json"
        memory_file_a.parent.mkdir(parents=True)
        memory_file_a.write_text(json.dumps({"version": "1.0", "facts": [{"content": "v1"}]}))
        memory_file_b = tmp_path / "tenant-b" / "memory.json"
        memory_file_b.parent.mkdir(parents=True)
        memory_file_b.write_text(json.dumps({"version": "1.0", "facts": [{"content": "v1"}]}))

        storage = FileMemoryStorage()

        with patch("deerflow.agents.memory.storage.get_memory_config", return_value=MemoryConfig(storage_path="")):
            with patch("deerflow.agents.memory.storage.get_paths") as mock_get_paths:
                mock_get_paths.return_value = MagicMock(memory_file=memory_file_a)
                token_a = set_current_tenant_id("tenant-a")
                try:
                    storage.load()
                finally:
                    reset_tenant_id(token_a)

                mock_get_paths.return_value = MagicMock(memory_file=memory_file_b)
                token_b = set_current_tenant_id("tenant-b")
                try:
                    storage.load()
                finally:
                    reset_tenant_id(token_b)

                mock_get_paths.return_value = MagicMock(memory_file=memory_file_a)
                token_a2 = set_current_tenant_id("tenant-a")
                try:
                    storage.reload()
                finally:
                    reset_tenant_id(token_a2)

                assert ("tenant-a", None) in storage._memory_cache
                assert ("tenant-b", None) in storage._memory_cache
