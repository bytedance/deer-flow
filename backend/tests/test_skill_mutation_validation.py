"""P0 changes preserve authority declarations and capture a bounded exact package."""

import os

import pytest

from deerflow.skills.mutations.assets import capture_package
from deerflow.skills.mutations.validation import validate_candidate

BASE = "---\nname: example\ndescription: Before\nallowed-tools: [Read]\nsecrets-autonomous: false\nmetadata: {custom: 1}\nfuture-field: {enabled: true}\n---\nBefore body\n"


def test_only_body_and_description_may_change():
    validate_candidate(BASE, BASE.replace("Before", "After"), "example")


@pytest.mark.parametrize(
    "old,new",
    [
        ("allowed-tools: [Read]\n", ""),
        ("allowed-tools: [Read]", "allowed-tools: []"),
        ("secrets-autonomous: false", "secrets-autonomous: true"),
        ("custom: 1", "custom: true"),
        ("future-field: {enabled: true}\n", ""),
        ("name: example", "name: renamed"),
    ],
)
def test_behavior_and_unknown_fields_preserve_values_and_types(old, new):
    with pytest.raises(ValueError, match="FRONTMATTER_CHANGED"):
        validate_candidate(BASE, BASE.replace(old, new), "example")


@pytest.mark.parametrize("extra", ["description: Duplicate\n", "metadata: &x {a: 1}\nfuture: *x\n", "metadata: {a: 1, a: 2}\n", "1: value\n"])
def test_ambiguous_yaml_is_rejected(extra):
    candidate = "---\nname: example\ndescription: Valid\n" + extra + "---\nBody"
    with pytest.raises(ValueError, match="INVALID_FRONTMATTER"):
        validate_candidate(candidate, candidate, "example")


@pytest.mark.parametrize("description", ["", "[]", "null", "'<bad>'"])
def test_description_remains_runtime_valid(description):
    with pytest.raises(ValueError, match="INVALID_FRONTMATTER"):
        validate_candidate(BASE, BASE.replace("description: Before", f"description: {description}"), "example")


def test_main_file_size_is_bounded():
    with pytest.raises(ValueError, match="QUOTA_EXCEEDED"):
        validate_candidate(BASE, BASE + "x" * (128 * 1024), "example")


def test_non_finite_frontmatter_has_stable_error_code():
    content = BASE.replace("custom: 1", "custom: .nan")
    with pytest.raises(ValueError, match="INVALID_FRONTMATTER"):
        validate_candidate(content, content, "example")


def test_package_snapshot_covers_support_bytes_and_execute_flags(tmp_path):
    (tmp_path / "SKILL.md").write_text(BASE, encoding="utf-8")
    support = tmp_path / "script.sh"
    support.write_bytes(b"echo before\n")
    first = capture_package(tmp_path)
    assert first.main_content == BASE
    assert first == capture_package(tmp_path)
    support.write_bytes(b"echo after\n")
    assert first.digest != capture_package(tmp_path).digest
    before_mode = capture_package(tmp_path)
    support.chmod(0o755)
    assert before_mode.digest != capture_package(tmp_path).digest


def test_snapshot_detached_from_live_files(tmp_path):
    main = tmp_path / "SKILL.md"
    main.write_text(BASE, encoding="utf-8")
    captured = capture_package(tmp_path)
    main.write_text("changed", encoding="utf-8")
    assert captured.main_content == BASE


@pytest.mark.skipif(os.name != "posix", reason="POSIX publication contract")
def test_capture_refuses_symlinked_ancestor(tmp_path):
    real = tmp_path / "real" / "example"
    real.mkdir(parents=True)
    (real / "SKILL.md").write_text(BASE, encoding="utf-8")
    (tmp_path / "alias").symlink_to(tmp_path / "real", target_is_directory=True)
    with pytest.raises(ValueError, match="UNSUPPORTED_ASSET"):
        capture_package(tmp_path / "alias" / "example")


@pytest.mark.parametrize("kind", ["root-link", "main-link", "support-link", "directory-link", "fifo"])
@pytest.mark.skipif(os.name != "posix", reason="POSIX publication contract")
def test_automatic_capture_rejects_links_and_special_files(tmp_path, kind):
    root = tmp_path / "skill"
    root.mkdir()
    (root / "SKILL.md").write_text(BASE, encoding="utf-8")
    if kind == "root-link":
        alias = tmp_path / "alias"
        alias.symlink_to(root, target_is_directory=True)
        root = alias
    elif kind == "main-link":
        (root / "SKILL.md").unlink()
        (root / "SKILL.md").symlink_to(tmp_path / "missing")
    elif kind == "support-link":
        (root / "support").symlink_to(tmp_path / "missing")
    elif kind == "directory-link":
        (root / "refs").symlink_to(tmp_path, target_is_directory=True)
    else:
        os.mkfifo(root / "pipe")
    with pytest.raises(ValueError, match="UNSUPPORTED_ASSET"):
        capture_package(root)


def test_snapshot_never_returns_a_partially_captured_package(tmp_path):
    (tmp_path / "SKILL.md").write_text(BASE, encoding="utf-8")
    for index in range(256):
        (tmp_path / f"support-{index}").touch()
    with pytest.raises(ValueError, match="QUOTA_EXCEEDED"):
        capture_package(tmp_path)
