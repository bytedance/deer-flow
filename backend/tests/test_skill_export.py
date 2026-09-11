import os
import zipfile

import pytest

from deerflow.skills import export
from deerflow.skills.storage.local_skill_storage import LocalSkillStorage


@pytest.fixture
def package(tmp_path):
    storage = LocalSkillStorage(host_path=str(tmp_path))
    root = tmp_path / "custom" / "sample"
    root.mkdir(parents=True)
    (root / "SKILL.md").write_bytes(b"---\nname: sample\ndescription: Example\n---\nHello\r\n")
    return storage, root


def test_snapshot_revision_and_zip_roundtrip(package, tmp_path):
    storage, root = package
    (root / "empty").mkdir()
    (root / "run.sh").write_bytes(b"#!/bin/sh\necho hello\n")
    (root / "run.sh").chmod(0o751)
    manifest = export.export_manifest(storage, "sample")
    assert manifest["can_export"] and manifest["directory_count"] == 2
    archive = export.build_skill_export(storage, "sample", manifest["revision"])
    try:
        with zipfile.ZipFile(archive.file) as z:
            assert z.read("sample/SKILL.md") == (root / "SKILL.md").read_bytes()
            from deerflow.skills.installer import safe_extract_skill_archive

            safe_extract_skill_archive(z, tmp_path / "imported")
        assert (tmp_path / "imported/sample/empty").is_dir()
        if os.name == "posix":
            assert (tmp_path / "imported/sample/run.sh").stat().st_mode & 0o7777 == 0o755
    finally:
        archive.close()
    (root / "run.sh").chmod(0o644)
    with pytest.raises(export.SkillExportError, match="changed") as error:
        export.build_skill_export(storage, "sample", manifest["revision"])
    assert error.value.status == 409


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "nested", "reserved", "binary", "collision"])
def test_structural_blockers(package, kind):
    storage, root = package
    if kind == "symlink":
        (root / "link").symlink_to(root / "SKILL.md")
    elif kind == "hardlink":
        os.link(root / "SKILL.md", root / "hard")
    elif kind == "nested":
        (root / "nested").mkdir()
        (root / "nested/SKILL.md").write_text("fixture")
    elif kind == "reserved":
        (root / "CON.txt").touch()
    elif kind == "binary":
        (root / "elf").write_bytes(b"\x7fELFhello")
    else:
        (root / "A").touch()
        (root / "a").touch()
        if len(list(root.iterdir())) < 3:
            pytest.skip("case insensitive filesystem")
    manifest = export.export_manifest(storage, "sample")
    assert not manifest["can_export"] and manifest["revision"] is None
    assert manifest["blockers"]


def test_limits_are_not_truncated(package, monkeypatch):
    storage, root = package
    monkeypatch.setattr(export, "MAX_ENTRIES", 1)
    with pytest.raises(export.SkillExportError) as error:
        export.export_manifest(storage, "sample")
    assert error.value.status == 413


def test_root_link_and_missing_ownership(package):
    storage, root = package
    root.rename(root.with_name("other"))
    root.symlink_to(root.with_name("other"), target_is_directory=True)
    assert export.export_manifest(storage, "sample")["blockers"][0]["code"] == "skill_export_link"
    with pytest.raises(export.SkillExportError) as error:
        export.export_manifest(storage, "missing")
    assert error.value.status == 404


def test_local_writer_waits_for_export_lock(package):
    import threading

    from deerflow.skills.projection import skill_projection_read_lock

    storage, root = package
    started = threading.Event()
    finished = threading.Event()

    def write():
        started.set()
        storage.write_custom_skill("sample", "new/resource.txt", "new")
        finished.set()

    with skill_projection_read_lock(storage):
        thread = threading.Thread(target=write)
        thread.start()
        assert started.wait(1)
        assert not finished.wait(0.1)
        assert not (root / "new").exists()
    thread.join(2)
    assert finished.is_set()


def test_snapshot_source_race(package, monkeypatch):
    storage, root = package
    original = export._walk

    def racing(*args):
        result = original(*args)
        (root / "SKILL.md").write_bytes((root / "SKILL.md").read_bytes() + b"changed")
        return result

    monkeypatch.setattr(export, "_walk", racing)
    with pytest.raises(export.SkillExportError) as error:
        export.export_manifest(storage, "sample")
    assert error.value.status == 409


def test_zip_uses_only_snapshot(package, monkeypatch):
    storage, root = package
    manifest = export.export_manifest(storage, "sample")
    original_bytes = (root / "SKILL.md").read_bytes()
    original = export._capture

    def replace_after_capture(*args):
        result = original(*args)
        (root / "SKILL.md").write_bytes(b"new content")
        return result

    monkeypatch.setattr(export, "_capture", replace_after_capture)
    archive = export.build_skill_export(storage, "sample", manifest["revision"])
    try:
        with zipfile.ZipFile(archive.file) as z:
            assert z.read("sample/SKILL.md") == original_bytes
    finally:
        archive.close()


@pytest.mark.parametrize("limit", ["MAX_FILE_BYTES", "MAX_TOTAL_BYTES", "MAX_PATH_BYTES", "MAX_DEPTH"])
def test_resource_limits(package, monkeypatch, limit):
    storage, root = package
    (root / "deep").mkdir()
    (root / "deep/file").write_bytes(b"abc")
    monkeypatch.setattr(export, limit, 1)
    with pytest.raises(export.SkillExportError) as error:
        export.export_manifest(storage, "sample")
    assert error.value.status == 413


def test_zip_limit_and_cancellation_close_files(package, monkeypatch):
    import threading

    storage, root = package
    manifest = export.export_manifest(storage, "sample")
    files = []
    original = export.tempfile.TemporaryFile

    def track(*args, **kwargs):
        file = original(*args, **kwargs)
        files.append(file)
        return file

    monkeypatch.setattr(export.tempfile, "TemporaryFile", track)
    monkeypatch.setattr(export, "MAX_ZIP_BYTES", 1)
    with pytest.raises(export.SkillExportError) as error:
        export.build_skill_export(storage, "sample", manifest["revision"])
    assert error.value.status == 413
    assert all(file.closed for file in files)
    event = threading.Event()
    event.set()
    with pytest.raises(export.SkillExportError) as error:
        export.export_manifest(storage, "sample", event)
    assert error.value.code == "skill_export_cancelled"
    assert all(file.closed for file in files)


def test_diagnostics_requirements_do_not_expose_contents(package):
    import json

    storage, root = package
    (root / ".env").write_text("SECRET_VALUE=private-contents", encoding="utf-8")
    (root / "SKILL.md").write_text("---\nname: sample\ndescription: Example\ncompatibility: Requires Python\nrequired-secrets:\n  - name: API_KEY\n    optional: true\n    value: private-contents\n---\n", encoding="utf-8")
    manifest = export.export_manifest(storage, "sample")
    assert manifest["requirements"]["required_secrets"] == [{"name": "API_KEY", "optional": True}]
    assert manifest["warnings"]
    assert "private-contents" not in json.dumps(manifest)


@pytest.mark.parametrize("skill_name", ["code-documentation", "skill-creator"])
def test_public_skill_real_install_roundtrip(tmp_path, monkeypatch, skill_name):
    import shutil
    from pathlib import Path
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from deerflow.skills import installer

    public = Path(__file__).resolve().parents[2] / "skills/public" / skill_name
    storage = LocalSkillStorage(host_path=str(tmp_path / "source"))
    root = storage.get_custom_skill_dir(skill_name)
    shutil.copytree(public, root, ignore=shutil.ignore_patterns("__pycache__"))
    manifest = export.export_manifest(storage, skill_name)
    assert manifest["can_export"], manifest["blockers"]
    archive = export.build_skill_export(storage, skill_name, manifest["revision"])
    archive_path = tmp_path / "code-documentation.skill"
    try:
        archive_path.write_bytes(archive.file.read())
    finally:
        archive.close()
    # Run the real installer and deterministic scanner; substitute only the remote LLM decision.
    scan = AsyncMock(return_value=SimpleNamespace(decision="allow", reason="test approval"))
    monkeypatch.setattr(installer, "scan_skill_content", scan)
    target = LocalSkillStorage(host_path=str(tmp_path / "target"), app_config=SimpleNamespace(skill_scan=SimpleNamespace(enabled=True)))
    result = target.install_skill_from_archive(archive_path)
    assert result["success"]
    assert scan.called
    assert export.export_manifest(target, skill_name)["revision"] == manifest["revision"]
    if skill_name == "skill-creator":
        import subprocess
        import sys

        installed = target.get_custom_skill_dir(skill_name)
        result = subprocess.run([sys.executable, str(installed / "scripts/quick_validate.py"), str(installed)], capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "Skill is valid!" in result.stdout


@pytest.mark.parametrize("mode, expected", [(0o100777, 0o755), (0o107777, 0o755), (0o100640, 0o644), (0, 0o644)])
def test_import_permissions_from_independent_zip(tmp_path, mode, expected):
    import io

    from deerflow.skills.installer import safe_extract_skill_archive

    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w") as archive:
        info = zipfile.ZipInfo("script")
        info.create_system = 3
        info.external_attr = mode << 16
        archive.writestr(info, b"#!/bin/sh\n")
    raw.seek(0)
    with zipfile.ZipFile(raw) as archive:
        safe_extract_skill_archive(archive, tmp_path)
    if os.name == "posix":
        assert (tmp_path / "script").stat().st_mode & 0o7777 == expected


def test_cross_process_lock_timeout(package, monkeypatch):
    import subprocess
    import sys

    storage, root = package
    lock = root.parent.parent / ".custom.projection.lock"
    child = subprocess.Popen([sys.executable, "-c", 'import fcntl,sys,time; f=open(sys.argv[1],"a"); fcntl.flock(f,fcntl.LOCK_EX); print("ready",flush=True); time.sleep(10)', str(lock)], stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "ready"
        monkeypatch.setattr(export, "LOCK_TIMEOUT_SECONDS", 0.05)
        with pytest.raises(export.SkillExportError) as error:
            export.export_manifest(storage, "sample")
        assert error.value.code == "skill_export_timeout"
    finally:
        child.terminate()
        child.wait(timeout=2)
        child.stdout.close()


def test_user_read_lock_no_projection_mutation_and_owned_only(tmp_path, monkeypatch):
    from deerflow.config.paths import Paths
    from deerflow.skills.projection import get_skill_projection_paths
    from deerflow.skills.storage.user_scoped_skill_storage import UserScopedSkillStorage

    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: Paths(base_dir=tmp_path))
    storage = UserScopedSkillStorage("one", host_path=str(tmp_path / "global"))
    legacy = tmp_path / "global/custom/sample"
    legacy.mkdir(parents=True)
    (legacy / "SKILL.md").write_text("---\nname: sample\ndescription: Example\n---\n", encoding="utf-8")
    with pytest.raises(export.SkillExportError) as error:
        export.export_manifest(storage, "sample")
    assert error.value.status == 404
    import shutil

    shutil.copytree(legacy, storage.get_custom_skill_dir("sample"))
    scope = get_skill_projection_paths(storage).custom.parent
    scope.mkdir(parents=True, exist_ok=True)
    marker = scope / ".projection-manifest.json"
    marker.write_text("unchanged", encoding="utf-8")
    assert export.export_manifest(storage, "sample")["can_export"]
    assert marker.read_text(encoding="utf-8") == "unchanged"


@pytest.mark.parametrize("user_scoped", [False, True])
def test_temp_creation_and_cleanup_within_mutation(tmp_path, monkeypatch, user_scoped):
    from contextlib import contextmanager

    from deerflow.config.paths import Paths
    from deerflow.skills.storage.user_scoped_skill_storage import UserScopedSkillStorage

    monkeypatch.setattr("deerflow.config.paths.get_paths", lambda: Paths(base_dir=tmp_path))
    storage = UserScopedSkillStorage("one", host_path=str(tmp_path)) if user_scoped else LocalSkillStorage(host_path=str(tmp_path))
    root = storage.get_custom_skill_dir("sample")
    active = False

    @contextmanager
    def locked():
        nonlocal active
        assert not root.exists()
        active = True
        try:
            yield
        finally:
            assert list(root.iterdir()) == []
            active = False

    monkeypatch.setattr(storage, "_skill_projection_mutation", locked)
    from deerflow.skills.storage import local_skill_storage

    original = local_skill_storage.tempfile.NamedTemporaryFile

    @contextmanager
    def failing(*args, **kwargs):
        assert active
        with original(*args, **kwargs) as file:

            class Broken:
                name = file.name

                def write(self, content):
                    file.write(content)
                    raise OSError("simulated write failure")

            yield Broken()

    monkeypatch.setattr(local_skill_storage.tempfile, "NamedTemporaryFile", failing)
    with pytest.raises(OSError):
        storage.write_custom_skill("sample", "SKILL.md", "abc")
    assert not active


def test_ancestor_symlink_is_not_followed(package, tmp_path):
    storage, root = package
    # A user scope ancestor is also an ownership boundary, even if custom itself is real.
    custom = root.parent
    custom.rename(tmp_path / "outside")
    (tmp_path / "scope").symlink_to(tmp_path, target_is_directory=True)
    storage.get_custom_skill_dir = lambda name: tmp_path / "scope/outside" / name
    manifest = export.export_manifest(storage, "sample")
    assert not manifest["can_export"]
    assert manifest["blockers"][0]["code"] == "skill_export_link"


def test_nofollow_file_replacement_is_changed(package, monkeypatch):
    storage, root = package
    original = export.os.open
    swapped = False

    def racing(path, flags, *args, **kwargs):
        nonlocal swapped
        if path == "SKILL.md" and not swapped:
            swapped = True
            (root / "SKILL.md").unlink()
            (root / "SKILL.md").symlink_to("/etc/hosts")
        return original(path, flags, *args, **kwargs)

    monkeypatch.setattr(export.os, "open", racing)
    monkeypatch.setattr(export.os, "supports_dir_fd", os.supports_dir_fd | {racing})
    with pytest.raises(export.SkillExportError) as error:
        export.export_manifest(storage, "sample")
    assert error.value.status == 409


def test_large_body_and_bounded_frontmatter(package):
    storage, root = package
    header = (root / "SKILL.md").read_bytes()
    (root / "SKILL.md").write_bytes(header + b"body\n" * 250000)
    assert export.export_manifest(storage, "sample")["can_export"]
    (root / "SKILL.md").write_bytes(b"---\nname: sample\ndescription: Example\ncompatibility: " + b"x" * (1024 * 1024) + b"\n---\n")
    with pytest.raises(export.SkillExportError) as error:
        export.export_manifest(storage, "sample")
    assert error.value.status == 413


def test_invalid_utf8_in_large_body_is_blocked(package):
    storage, root = package
    (root / "SKILL.md").write_bytes((root / "SKILL.md").read_bytes() + b"x" * (1024 * 1024 + 1) + b"\xff")
    assert not export.export_manifest(storage, "sample")["can_export"]


@pytest.mark.parametrize("name", ["con", "aux", "com1"])
def test_windows_reserved_root_is_blocked(tmp_path, name):
    storage = LocalSkillStorage(host_path=str(tmp_path))
    root = storage.get_custom_skill_dir(name)
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text(f"---\nname: {name}\ndescription: Example\n---\n", encoding="utf-8")
    assert not export.export_manifest(storage, name)["can_export"]


def test_required_secrets_normalization_and_invalid_warning(package):
    storage, root = package
    (root / "SKILL.md").write_text('---\nname: sample\ndescription: Example\nrequired-secrets:\n - " API_KEY "\n - name: API_KEY\n - name: " OPTIONAL_KEY "\n   optional: true\n - name: []\n - 123\n---\n', encoding="utf-8")
    manifest = export.export_manifest(storage, "sample")
    assert manifest["requirements"]["required_secrets"] == [{"name": "API_KEY", "optional": False}, {"name": "OPTIONAL_KEY", "optional": True}]
    assert any(warning["code"] == "skill_export_invalid_declaration" for warning in manifest["warnings"])


def test_mtime_does_not_change_revision(package):
    storage, root = package
    before = export.export_manifest(storage, "sample")["revision"]
    os.utime(root / "SKILL.md", (1, 1))
    assert export.export_manifest(storage, "sample")["revision"] == before


def test_deep_yaml_is_bounded_without_source_diagnostics(package):
    storage, root = package
    (root / "SKILL.md").write_text("---\nname: sample\ndescription: " + "[" * 5000 + "secret" + "]" * 5000 + "\n---\n", encoding="utf-8")
    manifest = export.export_manifest(storage, "sample")
    assert not manifest["can_export"]
    assert "secret" not in str(manifest["blockers"])


def test_invalid_unicode_nodes_still_consume_entry_budget(package, monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace

    storage, root = package
    (root / "one").mkdir()
    (root / "two").mkdir()
    directory_inodes = {(root / "one").stat().st_ino, (root / "two").stat().st_ino}
    original = export.os.scandir

    @contextmanager
    def names(fd):
        if os.fstat(fd).st_ino in directory_inodes:
            yield iter([SimpleNamespace(name="\udcff")])
        else:
            with original(fd) as iterator:
                yield iterator

    monkeypatch.setattr(export.os, "scandir", names)
    monkeypatch.setattr(export.os, "supports_fd", os.supports_fd | {names})
    monkeypatch.setattr(export, "MAX_ENTRIES", 4)
    with pytest.raises(export.SkillExportError) as error:
        export.export_manifest(storage, "sample")
    assert error.value.status == 413


@pytest.mark.parametrize("metadata", ["metadata: {base: &base {x: 1}, copy: *base}", "description: &text Example\nmetadata: {copy: *text}"])
def test_yaml_alias_is_rejected_before_constructor(package, monkeypatch, metadata):
    storage, root = package
    (root / "SKILL.md").write_text("---\nname: sample\ndescription: Example\n" + metadata + "\n---\n", encoding="utf-8")

    def forbidden(*args, **kwargs):
        raise AssertionError("YAML constructor must not run for aliases")

    monkeypatch.setattr(export, "validate_skill_frontmatter_text", forbidden)
    manifest = export.export_manifest(storage, "sample")
    assert not manifest["can_export"]
    assert manifest["blockers"][0]["code"] == "skill_export_yaml_alias"
    assert "aliases" in manifest["blockers"][0]["message"]


def test_yaml_merge_alias_bomb_is_blocked_without_expansion(package):
    storage, root = package
    levels = ["  a0: &a0 {x: 1}"]
    levels.extend(f"  a{i}: &a{i} {{<<: [*a{i - 1}, *a{i - 1}]}}" for i in range(1, 31))
    content = "---\nname: sample\ndescription: Example\nmetadata:\n" + "\n".join(levels) + "\n---\n"
    (root / "SKILL.md").write_text(content, encoding="utf-8")
    manifest = export.export_manifest(storage, "sample")
    assert not manifest["can_export"]
    assert manifest["blockers"][0]["code"] == "skill_export_yaml_alias"


@pytest.mark.parametrize("kind", ["depth", "events"])
def test_yaml_structural_budget_precedes_constructor(package, monkeypatch, kind):
    storage, root = package
    extra = "metadata: " + "[" * 40 + "x" + "]" * 40 if kind == "depth" else "metadata: [" + ",".join("x" for _ in range(20)) + "]"
    if kind == "events":
        monkeypatch.setattr(export, "MAX_YAML_EVENTS", 16)
    (root / "SKILL.md").write_text("---\nname: sample\ndescription: Example\n" + extra + "\n---\n", encoding="utf-8")

    def forbidden(*args, **kwargs):
        raise AssertionError("YAML constructor must not run over structural budget")

    monkeypatch.setattr(export, "validate_skill_frontmatter_text", forbidden)
    manifest = export.export_manifest(storage, "sample")
    assert not manifest["can_export"]
    assert manifest["blockers"][0]["code"] == "skill_export_yaml_complexity"


def test_yaml_event_preflight_observes_cancellation(package, monkeypatch):
    import threading

    storage, root = package
    event = threading.Event()
    original = export.yaml.parse

    def cancel_during_parse(*args, **kwargs):
        for parsed in original(*args, **kwargs):
            event.set()
            yield parsed

    monkeypatch.setattr(export.yaml, "parse", cancel_during_parse)
    with pytest.raises(export.SkillExportError) as error:
        export.export_manifest(storage, "sample", event)
    assert error.value.code == "skill_export_cancelled"
