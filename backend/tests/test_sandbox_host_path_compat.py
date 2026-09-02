from __future__ import annotations

import pytest
from pydantic import ValidationError

from deerflow.config.sandbox_config import VolumeMountConfig
from deerflow.sandbox.host_path_compat import (
    is_program_argument_path,
    normalize_host_path,
    replace_host_paths_in_command,
    split_program_argument,
)


@pytest.fixture
def mounts() -> list[VolumeMountConfig]:
    return [
        VolumeMountConfig(
            host_path="C:/Users/lichen",
            container_path="/root",
            read_only=False,
        )
    ]


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (r"C:\Users\lichen\x", "/root/x"),
        ("C:/Users/lichen/x", "/root/x"),
        ("/c/Users/lichen/x", "/root/x"),
        (r"c:\USERS\LICHEN\x", "/root/x"),
        ("C:/Users/lichen", "/root"),
    ],
)
def test_normalize_host_path_accepts_windows_spellings(mounts: list[VolumeMountConfig], path: str, expected: str) -> None:
    assert normalize_host_path(path, mounts) == expected


def test_normalize_host_path_uses_the_most_specific_configured_mount() -> None:
    mounts = [
        VolumeMountConfig(host_path="C:/Users/lichen", container_path="/root", read_only=False),
        VolumeMountConfig(host_path="C:/Users/lichen/project", container_path="/workspace", read_only=False),
    ]

    assert normalize_host_path(r"C:\Users\lichen\project\src", mounts) == "/workspace/src"


def test_normalize_host_path_accepts_a_windows_drive_root_mount() -> None:
    mounts = [VolumeMountConfig(host_path="C:/", container_path="/drive-c", read_only=False)]

    assert normalize_host_path(r"C:\Users\lichen\x", mounts) == "/drive-c/Users/lichen/x"


def test_normalize_host_path_accepts_a_single_volume_mount() -> None:
    mount = VolumeMountConfig(host_path="C:/Users/lichen", container_path="/root", read_only=False)

    assert normalize_host_path(r"C:\Users\lichen\x", mount) == "/root/x"


@pytest.mark.parametrize(
    "path",
    [
        "C:/Users/lichen2/file.txt",
        r"C:\Users\lichen\..\other\secret.txt",
        "D:/Users/lichen/file.txt",
        "/c/Users/other/file.txt",
    ],
)
def test_normalize_host_path_rejects_paths_outside_configured_mount(mounts: list[VolumeMountConfig], path: str) -> None:
    with pytest.raises(PermissionError):
        normalize_host_path(path, mounts)


def test_replace_host_paths_in_command_preserves_quotes_and_non_path_text(
    mounts: list[VolumeMountConfig],
) -> None:
    command = r"""python "C:\Users\lichen\scripts\run.py" --label="keep this" && echo /c/Users/lichen/out.txt"""

    assert replace_host_paths_in_command(command, mounts) == 'python "/root/scripts/run.py" --label="keep this" && echo /root/out.txt'


def test_replace_host_paths_in_command_handles_unquoted_path_before_arguments(
    mounts: list[VolumeMountConfig],
) -> None:
    command = r"find C:\Users\lichen -mindepth 1 -maxdepth 1 -type d"

    assert replace_host_paths_in_command(command, mounts) == "find /root -mindepth 1 -maxdepth 1 -type d"


def test_replace_host_paths_in_command_handles_quoted_path_with_spaces(
    mounts: list[VolumeMountConfig],
) -> None:
    command = r'''python "C:\Users\lichen\My Tools\run.py" --config "C:\Users\lichen\config.tfx-dms"'''

    assert replace_host_paths_in_command(command, mounts) == 'python "/root/My Tools/run.py" --config "/root/config.tfx-dms"'


def test_replace_host_paths_in_command_leaves_commands_without_host_paths_unchanged(
    mounts: list[VolumeMountConfig],
) -> None:
    command = "echo https://example.test/a/b && ls /tmp/plain.txt && printf 'plain text'"

    assert replace_host_paths_in_command(command, mounts) == command


@pytest.mark.parametrize("command", ["curl http://c/foo", "curl https://a/bar", "echo x://c/foo"])
def test_replace_host_paths_in_command_does_not_treat_url_hosts_as_git_bash_paths(mounts: list[VolumeMountConfig], command: str) -> None:
    assert replace_host_paths_in_command(command, mounts) == command


def test_replace_host_paths_in_command_rejects_unconfigured_host_paths(
    mounts: list[VolumeMountConfig],
) -> None:
    with pytest.raises(PermissionError):
        replace_host_paths_in_command(r'echo "C:\Users\lichen2\secret.txt"', mounts)


def test_volume_mount_rejects_drive_shaped_container_path() -> None:
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr("deerflow.config.sandbox_config.os.name", "nt")
        with pytest.raises(ValidationError, match="drive-shaped"):
            VolumeMountConfig(
                host_path="C:/Users/lichen",
                container_path="/c/projects",
                read_only=False,
            )


def test_volume_mount_allows_single_letter_posix_root_on_non_windows() -> None:
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr("deerflow.config.sandbox_config.os.name", "posix")
        mount = VolumeMountConfig(
            host_path="/tmp",
            container_path="/d/data",
            read_only=False,
        )

    assert mount.container_path == "/d/data"


def test_volume_mount_rejects_drive_path_on_non_windows() -> None:
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr("deerflow.config.sandbox_config.os.name", "posix")
        with pytest.raises(ValidationError, match="drive-shaped"):
            VolumeMountConfig(
                host_path="/tmp",
                container_path="C:/projects",
                read_only=False,
            )


def test_normalize_host_path_preserves_single_letter_posix_container_root() -> None:
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr("deerflow.config.sandbox_config.os.name", "posix")
        monkeypatch.setattr("deerflow.sandbox.host_path_compat.os.name", "posix")
        mount = VolumeMountConfig(host_path="/tmp", container_path="/d/data", read_only=False)
        assert normalize_host_path("/tmp/report.txt", mount) == "/d/data/report.txt"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("--config=/root/config.tfx-dms", ("--config=", "/root/config.tfx-dms")),
        (r"/out:C:\Windows\secret.txt", ("/out:", r"C:\Windows\secret.txt")),
        (r"/LIBPATH:C:\outside", ("/LIBPATH:", r"C:\outside")),
        (r"@C:\outside\args.rsp", ("@", r"C:\outside\args.rsp")),
        ("--mode=release", ("--mode=", "release")),
        ("https://example.test/path", ("", "https://example.test/path")),
        ("url:http://example.test/path", ("", "url:http://example.test/path")),
        ("file:///C:/Windows/secret.txt", ("", "file:///C:/Windows/secret.txt")),
        ("--input=file:///C:/Windows/secret.txt", ("", "--input=file:///C:/Windows/secret.txt")),
        ("/out:FILE:///C:/Windows/secret.txt", ("", "/out:FILE:///C:/Windows/secret.txt")),
    ],
)
def test_split_program_argument_preserves_option_prefix(value: str, expected: tuple[str, str]) -> None:
    assert split_program_argument(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        r"C:\Windows\secret.txt",
        r"C:Windows\secret.txt",
        r"/c/Windows/secret.txt",
        r"\\host\share\secret.txt",
        "/etc/passwd",
        r"..\..\Windows\System32\calc.exe",
        r"/out:C:\Windows\secret.txt",
        r"@C:\Windows\args.rsp",
        "file:///C:/Windows/secret.txt",
        "--input=file:///C:/Windows/secret.txt",
        "@file:///C:/Windows/args.rsp",
        "FILE:///etc/passwd",
        "/out:file:///C:/Windows/secret.txt",
        " file:///etc/passwd ",
    ],
)
def test_program_argument_path_predicate_covers_rooted_drive_and_traversal_forms(value: str) -> None:
    assert is_program_argument_path(value)


@pytest.mark.parametrize(
    "value",
    [
        "--mode=release",
        "relative/file.txt",
        "https://example.test/path",
        "url:http://example.test/path",
        "https://example.test/?next=file:///C:/Windows/secret.txt",
        "--url=https://example.test/?next=file:///C:/Windows/secret.txt",
        "http://example.test/?x=file:///etc/passwd",
        "@https://example.test/?x=file:///etc/passwd",
        "https://example.test/../etc/passwd",
        "--url=https://example.test/../etc/passwd",
        "HTTPS://example.test/../etc/passwd",
        "--url=HTTPS://example.test/../etc/passwd",
        "HTTPS://example.test/?next=FILE:///C:/Windows/secret.txt",
        " https://example.test/?next=file:///C:/Windows/secret.txt ",
    ],
)
def test_program_argument_path_predicate_keeps_non_path_arguments_opaque(value: str) -> None:
    assert not is_program_argument_path(value)
