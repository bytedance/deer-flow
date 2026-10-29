# SPDX-License-Identifier: MIT
"""Exercise file publication and rollback of the installed Lark skill pack."""

from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path

import pytest

from deerflow.config import paths as paths_module
from deerflow.config.paths import Paths
from deerflow.integrations import lark_cli


@pytest.mark.parametrize("file_kind", ["skill", "manifest"])
def test_failed_file_publish_preserves_previous_content(tmp_path, monkeypatch, file_kind):
    root = tmp_path / "lark-cli"
    skill_file = root / "lark-shared" / "SKILL.md"
    skill_file.parent.mkdir(parents=True)
    skill_file.write_text("---\nname: lark-shared\ndescription: 飞书说明\n---\n\n旧版正文\n", encoding="utf-8")
    manifest_file = root / lark_cli.LARK_CLI_MANIFEST_FILE
    manifest_file.write_text('{"content_sha256": "previous-digest"}\n', encoding="utf-8")
    target = skill_file if file_kind == "skill" else manifest_file
    previous = target.read_bytes()
    real_replace = os.replace

    def fail_target_replace(source, destination):
        if Path(destination) == target:
            raise OSError("injected file publication failure")
        return real_replace(source, destination)

    monkeypatch.setattr(lark_cli.os, "replace", fail_target_replace)
    with pytest.raises(OSError, match="injected file publication failure"):
        if file_kind == "skill":
            lark_cli._append_deerflow_lark_shared_guidance(root)
        else:
            lark_cli._write_manifest(root, {"lark-shared"}, version="v1.0.65", content_sha256="new-digest")

    assert target.read_bytes() == previous
    assert not list(root.rglob("*.tmp"))


def _make_archive(tmp_path: Path, revision: str) -> Path:
    archive = tmp_path / f"lark-{revision}.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for skill_name in lark_cli.LARK_SKILL_NAMES:
            content = f"---\nname: {skill_name}\ndescription: 飞书技能 {revision}\n---\n\n# {skill_name}\n\n{revision} 正文\n"
            zf.writestr(f"cli-1.0.65/skills/{skill_name}/SKILL.md", content)
            zf.writestr(f"cli-1.0.65/skills/{skill_name}/references/readme.md", f"{revision} 参考\n")
    return archive


def _snapshot(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("file_kind", ["skill", "manifest"])
def test_failed_reinstall_keeps_installed_pack_and_discards_staging(tmp_path, monkeypatch, file_kind):
    monkeypatch.setattr(paths_module, "_paths", Paths(base_dir=tmp_path / "home"))
    previous_archive = _make_archive(tmp_path, "previous")
    replacement_archive = _make_archive(tmp_path, "replacement")
    installed, digest = lark_cli._install_lark_skills_from_archive("alice", previous_archive)
    root = lark_cli.lark_integration_root("alice")
    previous = _snapshot(root)
    manifest = json.loads(previous[lark_cli.LARK_CLI_MANIFEST_FILE])
    assert manifest["content_sha256"] == digest
    assert set(manifest["skills"]) == set(installed)

    failed_destination: Path | None = None
    real_replace = os.replace

    def fail_staged_replace(source, destination):
        nonlocal failed_destination
        destination = Path(destination)
        is_selected_file = destination.name == lark_cli.LARK_CLI_MANIFEST_FILE if file_kind == "manifest" else destination.parent.name == "lark-shared" and destination.name == "SKILL.md"
        if is_selected_file:
            failed_destination = destination
            # The publish is still private, and the live body/manifest pair is intact.
            assert destination.is_relative_to(root.parent)
            assert not destination.is_relative_to(root)
            assert _snapshot(root) == previous
            raise OSError("injected staged publication failure")
        return real_replace(source, destination)

    monkeypatch.setattr(lark_cli.os, "replace", fail_staged_replace)
    with pytest.raises(OSError, match="injected staged publication failure"):
        lark_cli._install_lark_skills_from_archive("alice", replacement_archive)

    assert failed_destination is not None
    assert _snapshot(root) == previous
    assert not failed_destination.exists()
    assert not list(root.parent.glob(".installing-lark-cli-*"))
    assert not list(root.parent.glob(".replacing-*"))
