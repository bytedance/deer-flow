"""Tests for tenant-scoped path resolution."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from deerflow.config.paths import Paths, get_paths
from deerflow.config.tenant import (
    _DEFAULT_TENANT_ID,
    get_current_tenant_id,
    reset_tenant_id,
    set_current_tenant_id,
)


class TestTenantBaseDir:
    def test_default_tenant_uses_base_dir(self, tmp_path):
        paths = Paths(base_dir=tmp_path)
        assert paths.tenant_base_dir == tmp_path

    def test_named_tenant_uses_tenants_subdir(self, tmp_path):
        paths = Paths(base_dir=tmp_path)
        token = set_current_tenant_id("acme")
        try:
            assert paths.tenant_base_dir == tmp_path / "tenants" / "acme"
        finally:
            reset_tenant_id(token)

    def test_tenant_base_dir_not_created_automatically(self, tmp_path):
        paths = Paths(base_dir=tmp_path)
        token = set_current_tenant_id("acme")
        try:
            _ = paths.tenant_base_dir
            assert not (tmp_path / "tenants" / "acme").exists()
        finally:
            reset_tenant_id(token)


class TestMemoryFile:
    def test_default_tenant(self, tmp_path):
        paths = Paths(base_dir=tmp_path)
        assert paths.memory_file == tmp_path / "memory.json"

    def test_named_tenant(self, tmp_path):
        paths = Paths(base_dir=tmp_path)
        token = set_current_tenant_id("acme")
        try:
            assert paths.memory_file == tmp_path / "tenants" / "acme" / "memory.json"
        finally:
            reset_tenant_id(token)


class TestUserMdFile:
    def test_default_tenant(self, tmp_path):
        paths = Paths(base_dir=tmp_path)
        assert paths.user_md_file == tmp_path / "USER.md"

    def test_named_tenant(self, tmp_path):
        paths = Paths(base_dir=tmp_path)
        token = set_current_tenant_id("acme")
        try:
            assert paths.user_md_file == tmp_path / "tenants" / "acme" / "USER.md"
        finally:
            reset_tenant_id(token)


class TestAgentsDir:
    def test_default_tenant(self, tmp_path):
        paths = Paths(base_dir=tmp_path)
        assert paths.agents_dir == tmp_path / "agents"

    def test_named_tenant(self, tmp_path):
        paths = Paths(base_dir=tmp_path)
        token = set_current_tenant_id("acme")
        try:
            assert paths.agents_dir == tmp_path / "tenants" / "acme" / "agents"
        finally:
            reset_tenant_id(token)

    def test_agent_dir_default(self, tmp_path):
        paths = Paths(base_dir=tmp_path)
        assert paths.agent_dir("my-agent") == tmp_path / "agents" / "my-agent"

    def test_agent_dir_named_tenant(self, tmp_path):
        paths = Paths(base_dir=tmp_path)
        token = set_current_tenant_id("acme")
        try:
            assert paths.agent_dir("my-agent") == tmp_path / "tenants" / "acme" / "agents" / "my-agent"
        finally:
            reset_tenant_id(token)

    def test_agent_memory_file_default(self, tmp_path):
        paths = Paths(base_dir=tmp_path)
        assert paths.agent_memory_file("my-agent") == tmp_path / "agents" / "my-agent" / "memory.json"

    def test_agent_memory_file_named_tenant(self, tmp_path):
        paths = Paths(base_dir=tmp_path)
        token = set_current_tenant_id("acme")
        try:
            assert paths.agent_memory_file("my-agent") == tmp_path / "tenants" / "acme" / "agents" / "my-agent" / "memory.json"
        finally:
            reset_tenant_id(token)


class TestThreadDir:
    def test_default_tenant(self, tmp_path):
        paths = Paths(base_dir=tmp_path)
        assert paths.thread_dir("thread-1") == tmp_path / "threads" / "thread-1"

    def test_named_tenant(self, tmp_path):
        paths = Paths(base_dir=tmp_path)
        token = set_current_tenant_id("acme")
        try:
            assert paths.thread_dir("thread-1") == tmp_path / "tenants" / "acme" / "threads" / "thread-1"
        finally:
            reset_tenant_id(token)

    def test_rejects_traversal(self, tmp_path):
        paths = Paths(base_dir=tmp_path)
        with pytest.raises(ValueError, match="Invalid thread_id"):
            paths.thread_dir("../escape")

    def test_sandbox_work_dir_tenant_scoped(self, tmp_path):
        paths = Paths(base_dir=tmp_path)
        token = set_current_tenant_id("acme")
        try:
            expected = tmp_path / "tenants" / "acme" / "threads" / "t1" / "user-data" / "workspace"
            assert paths.sandbox_work_dir("t1") == expected
        finally:
            reset_tenant_id(token)


class TestHostThreadDir:
    def test_default_tenant(self, tmp_path):
        paths = Paths(base_dir=tmp_path)
        result = paths.host_thread_dir("thread-1")
        assert "threads" in result
        assert "thread-1" in result

    def test_named_tenant(self, tmp_path):
        paths = Paths(base_dir=tmp_path)
        token = set_current_tenant_id("acme")
        try:
            result = paths.host_thread_dir("thread-1")
            assert "tenants" in result
            assert "acme" in result
            assert "thread-1" in result
        finally:
            reset_tenant_id(token)


class TestDeleteThreadDir:
    def test_idempotent_missing_dir(self, tmp_path):
        paths = Paths(base_dir=tmp_path)
        paths.delete_thread_dir("nonexistent")

    def test_deletes_existing_dir(self, tmp_path):
        paths = Paths(base_dir=tmp_path)
        thread_dir = paths.thread_dir("thread-1")
        thread_dir.mkdir(parents=True)
        (thread_dir / "test.txt").write_text("data")
        assert thread_dir.exists()
        paths.delete_thread_dir("thread-1")
        assert not thread_dir.exists()


class TestEnsureThreadDirs:
    def test_creates_all_subdirs(self, tmp_path):
        paths = Paths(base_dir=tmp_path)
        paths.ensure_thread_dirs("thread-1")
        assert paths.sandbox_work_dir("thread-1").is_dir()
        assert paths.sandbox_uploads_dir("thread-1").is_dir()
        assert paths.sandbox_outputs_dir("thread-1").is_dir()
        assert paths.acp_workspace_dir("thread-1").is_dir()


class TestResolveVirtualPath:
    def test_resolves_output_file(self, tmp_path):
        paths = Paths(base_dir=tmp_path)
        paths.ensure_thread_dirs("thread-1")
        out = paths.sandbox_outputs_dir("thread-1") / "report.pdf"
        out.write_text("pdf")
        resolved = paths.resolve_virtual_path("thread-1", "/mnt/user-data/outputs/report.pdf")
        assert resolved == out

    def test_rejects_non_matching_prefix(self, tmp_path):
        paths = Paths(base_dir=tmp_path)
        with pytest.raises(ValueError, match="must start with"):
            paths.resolve_virtual_path("thread-1", "/etc/passwd")

    def test_rejects_traversal(self, tmp_path):
        paths = Paths(base_dir=tmp_path)
        paths.ensure_thread_dirs("thread-1")
        with pytest.raises(ValueError, match="traversal"):
            paths.resolve_virtual_path("thread-1", "/mnt/user-data/../../../etc/passwd")


class TestGetPathsSingleton:
    def test_returns_same_instance(self):
        p1 = get_paths()
        p2 = get_paths()
        assert p1 is p2
