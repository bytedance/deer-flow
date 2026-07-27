"""Regression anchors: integrations router must not block the event loop.

The Lark integration handlers are async FastAPI route handlers, but the work
they dispatch includes zip reads, filesystem staging, manifest writes, and
``lark-cli`` subprocess calls. Those phases must stay behind
``asyncio.to_thread``; if a future refactor runs them inline, the strict
Blockbuster gate raises ``BlockingError`` and these anchors fail.
"""

from __future__ import annotations

import asyncio
import os
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.gateway.routers import integrations
from deerflow.config import paths as paths_module
from deerflow.integrations import lark_cli

pytestmark = pytest.mark.asyncio


def _skill_content(name: str) -> str:
    return f"---\nname: {name}\ndescription: {name} integration skill\n---\n\n# {name}\n"


def _build_lark_archive(archive: Path) -> None:
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w") as zf:
        for skill_name in lark_cli.LARK_SKILL_NAMES:
            zf.writestr(f"cli-1.0.65/skills/{skill_name}/SKILL.md", _skill_content(skill_name))
            zf.writestr(f"cli-1.0.65/skills/{skill_name}/references/readme.md", f"# {skill_name}\n")


def _write_stub_lark_cli(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """#!/bin/sh
if [ "$1" = "--version" ]; then
  echo "v1.0.65"
  exit 0
fi

if [ "$1" = "auth" ] && [ "$2" = "login" ]; then
  echo "{}"
  exit 0
fi

if [ "$1" = "auth" ] && [ "$2" = "status" ]; then
  echo '{"identities":{"user":{"userName":"Alice"}}}'
  exit 0
fi

echo "{}"
exit 0
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _reset_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(paths_module, "_paths", None)


async def _config(tmp_path: Path) -> SimpleNamespace:
    skills_root = tmp_path / "skills"
    await asyncio.to_thread((skills_root / "public").mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread((skills_root / "custom").mkdir, parents=True, exist_ok=True)
    return SimpleNamespace(
        skills=SimpleNamespace(
            get_skills_path=lambda: skills_root,
            container_path="/mnt/skills",
            use="deerflow.skills.storage.local_skill_storage:LocalSkillStorage",
        )
    )


async def test_lark_install_route_does_not_block_event_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_paths(tmp_path, monkeypatch)
    config = await _config(tmp_path)
    archive = tmp_path / "fixtures" / "lark-cli.zip"
    await asyncio.to_thread(_build_lark_archive, archive)

    async def _allow_admin(*_args, **_kwargs) -> None:
        return None

    refresh_calls = 0

    async def _refresh_cache() -> None:
        nonlocal refresh_calls
        refresh_calls += 1

    monkeypatch.setenv(lark_cli.LARK_CLI_SOURCE_ARCHIVE_ENV, str(archive))
    monkeypatch.setattr(lark_cli, "probe_lark_cli", lambda: lark_cli.LarkCliProbe(available=True, path="/usr/bin/lark-cli", version="v1.0.65"))
    monkeypatch.setattr(lark_cli, "probe_lark_auth", lambda _user_id, **_kwargs: lark_cli.LarkAuthProbe(status="not_configured", message="not configured"))
    monkeypatch.setattr(integrations, "get_effective_user_id", lambda: "loop-user")
    monkeypatch.setattr(integrations, "require_admin_user", _allow_admin)
    monkeypatch.setattr(integrations, "refresh_skills_system_prompt_cache_async", _refresh_cache, raising=False)

    response = await integrations.install_lark(request=None, config=config)

    assert response.success is True
    assert refresh_calls == 1
    install_root = await asyncio.to_thread(lark_cli.lark_integration_root, "loop-user")
    assert await asyncio.to_thread((install_root / "lark-doc" / "SKILL.md").exists)


async def test_lark_auth_complete_route_does_not_block_event_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_paths(tmp_path, monkeypatch)
    config = await _config(tmp_path)
    cli_path = tmp_path / "bin" / "lark-cli"
    await asyncio.to_thread(_write_stub_lark_cli, cli_path)

    monkeypatch.setenv("PATH", f"{cli_path.parent}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setattr(integrations, "get_effective_user_id", lambda: "loop-user")

    response = await integrations.complete_lark_browser_auth(
        request=None,
        body=integrations.LarkAuthCompleteRequest(device_code="device-code"),
        config=config,
    )

    assert response.status.cli.available is True
    assert response.status.cli.version == "v1.0.65"
