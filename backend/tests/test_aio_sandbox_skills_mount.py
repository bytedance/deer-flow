"""Tests for AIO sandbox skills mount resolution."""

from __future__ import annotations

from pathlib import Path

from src.community.aio_sandbox.aio_sandbox_provider import AioSandboxProvider


class _SkillsConfig:
    def __init__(self, skills_path: Path, container_path: str = "/mnt/skills"):
        self._skills_path = skills_path
        self.container_path = container_path

    def get_skills_path(self) -> Path:
        return self._skills_path


class _AppConfig:
    def __init__(self, skills_path: Path, container_path: str = "/mnt/skills"):
        self.skills = _SkillsConfig(skills_path=skills_path, container_path=container_path)


def test_get_skills_mount_uses_configured_path_by_default(monkeypatch, tmp_path: Path):
    skills_path = tmp_path / "skills"
    skills_path.mkdir()

    monkeypatch.setattr(
        "src.community.aio_sandbox.aio_sandbox_provider.get_app_config",
        lambda: _AppConfig(skills_path=skills_path),
    )
    monkeypatch.delenv("DEER_FLOW_SKILLS_HOST_PATH", raising=False)

    assert AioSandboxProvider._get_skills_mount() == (str(skills_path), "/mnt/skills", True)


def test_get_skills_mount_prefers_host_path_override_when_exists(monkeypatch, tmp_path: Path):
    container_visible_skills_path = tmp_path / "container" / "skills"
    container_visible_skills_path.mkdir(parents=True)

    host_skills_path = tmp_path / "host" / "skills"
    host_skills_path.mkdir(parents=True)

    monkeypatch.setattr(
        "src.community.aio_sandbox.aio_sandbox_provider.get_app_config",
        lambda: _AppConfig(skills_path=container_visible_skills_path),
    )
    monkeypatch.setenv("DEER_FLOW_SKILLS_HOST_PATH", str(host_skills_path))

    assert AioSandboxProvider._get_skills_mount() == (str(host_skills_path.resolve()), "/mnt/skills", True)


def test_get_skills_mount_falls_back_when_host_override_missing(monkeypatch, tmp_path: Path):
    skills_path = tmp_path / "skills"
    skills_path.mkdir()

    missing_host_path = tmp_path / "missing" / "skills"

    monkeypatch.setattr(
        "src.community.aio_sandbox.aio_sandbox_provider.get_app_config",
        lambda: _AppConfig(skills_path=skills_path),
    )
    monkeypatch.setenv("DEER_FLOW_SKILLS_HOST_PATH", str(missing_host_path))

    assert AioSandboxProvider._get_skills_mount() == (str(skills_path), "/mnt/skills", True)


def test_get_skills_mount_auto_resolves_bind_source_without_env(monkeypatch, tmp_path: Path):
    container_visible_skills_path = tmp_path / "container" / "skills"
    container_visible_skills_path.mkdir(parents=True)

    host_skills_path = tmp_path / "host" / "skills"
    host_skills_path.mkdir(parents=True)

    monkeypatch.setattr(
        "src.community.aio_sandbox.aio_sandbox_provider.get_app_config",
        lambda: _AppConfig(skills_path=container_visible_skills_path),
    )
    monkeypatch.delenv("DEER_FLOW_SKILLS_HOST_PATH", raising=False)
    monkeypatch.setattr(
        AioSandboxProvider,
        "_resolve_host_bind_path",
        classmethod(lambda cls, path: host_skills_path if path == container_visible_skills_path else None),
    )

    assert AioSandboxProvider._get_skills_mount() == (str(host_skills_path.resolve()), "/mnt/skills", True)
