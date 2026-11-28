"""Offline unit tests for video-generation multi-shot ffmpeg stitch script."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
STITCH_SCRIPT = REPO_ROOT / "skills" / "public" / "video-generation" / "scripts" / "stitch.sh"


def _make_fake_ffmpeg(bin_dir: Path, log_path: Path, *, mode: str = "ok") -> Path:
    """Create a fake ffmpeg executable that logs argv and manifest contents."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg_path = bin_dir / "ffmpeg"
    ffmpeg_path.write_text(
        f"""#!/usr/bin/env python3
import json
import sys
from pathlib import Path

args = sys.argv[1:]
manifest_text = None
if "-i" in args:
    manifest_path = Path(args[args.index("-i") + 1])
    if manifest_path.is_file():
        manifest_text = manifest_path.read_text(encoding="utf-8")

Path({str(log_path)!r}).write_text(
    json.dumps({{"args": args, "manifest": manifest_text}}),
    encoding="utf-8",
)

mode = {mode!r}
out_path = Path(args[-1])
if mode == "fail":
    sys.stderr.write("simulated ffmpeg failure\\n")
    sys.exit(1)
if mode == "empty":
    out_path.write_bytes(b"")
    sys.exit(0)

out_path.write_bytes(b"STITCHED_MP4_BYTES")
""",
        encoding="utf-8",
    )
    ffmpeg_path.chmod(ffmpeg_path.stat().st_mode | stat.S_IEXEC)
    return ffmpeg_path


def _env_with_bin(bin_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    return env


def _make_clips(tmp_path: Path, names: tuple[str, ...] = ("clip1.mp4", "clip2.mp4")) -> list[Path]:
    clips: list[Path] = []
    for idx, name in enumerate(names, start=1):
        clip = tmp_path / name
        clip.parent.mkdir(parents=True, exist_ok=True)
        clip.write_bytes(f"CLIP_{idx}_DATA".encode())
        clips.append(clip)
    return clips


def test_normalize_mode_stitches_clips_escapes_quotes_and_cleans_temp_dir(tmp_path):
    bin_dir = tmp_path / "bin"
    log_path = tmp_path / "ffmpeg_log.json"
    _make_fake_ffmpeg(bin_dir, log_path)

    clips = _make_clips(tmp_path, ("scene 1.mp4", "it's scene 2.mp4", "sub/scene_3.mp4"))
    out_file = tmp_path / "nested" / "outputs" / "final_ad.mp4"

    result = subprocess.run(
        [
            "bash",
            str(STITCH_SCRIPT),
            "--output-file",
            str(out_file),
            "--inputs",
            str(clips[0]),
            str(clips[1]),
            "sub/scene_3.mp4",
            "--fps",
            "24",
        ],
        cwd=tmp_path,
        env=_env_with_bin(bin_dir),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Stitched 3 clips successfully" in result.stdout
    assert out_file.read_bytes() == b"STITCHED_MP4_BYTES"

    # Temporary directory next to output must be cleaned up.
    leftovers = [p for p in out_file.parent.iterdir() if p.name.startswith(".stitch-tmp.")]
    assert leftovers == []

    recorded = json.loads(log_path.read_text(encoding="utf-8"))
    args = recorded["args"]
    assert "-f" in args and "concat" in args
    assert "-c:v" in args and "libx264" in args
    assert "-r" in args and "24" in args
    assert "-c:a" in args and "aac" in args
    assert "-movflags" in args and "+faststart" in args

    manifest_lines = recorded["manifest"].splitlines()
    assert len(manifest_lines) == 3
    assert manifest_lines[0] == f"file '{clips[0].resolve()}'"
    escaped_second = str(clips[1].resolve()).replace("'", "'\\''")
    assert manifest_lines[1] == f"file '{escaped_second}'"
    assert manifest_lines[2] == f"file '{clips[2].resolve()}'"


def test_copy_mode_and_mov_output_extension(tmp_path):
    bin_dir = tmp_path / "bin"
    log_path = tmp_path / "ffmpeg_log.json"
    _make_fake_ffmpeg(bin_dir, log_path)
    clips = _make_clips(tmp_path)
    out_file = tmp_path / "deliverable.MOV"

    result = subprocess.run(
        [
            "bash",
            str(STITCH_SCRIPT),
            "--output-file",
            str(out_file),
            "--inputs",
            str(clips[0]),
            str(clips[1]),
            "--mode",
            "copy",
        ],
        env=_env_with_bin(bin_dir),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert out_file.read_bytes() == b"STITCHED_MP4_BYTES"
    recorded = json.loads(log_path.read_text(encoding="utf-8"))
    args = recorded["args"]
    assert "-c" in args and "copy" in args
    assert "libx264" not in args
    assert "aac" not in args
    assert args[-1].endswith(".mov")


def test_in_place_output_matching_input_swaps_atomically(tmp_path):
    bin_dir = tmp_path / "bin"
    log_path = tmp_path / "ffmpeg_log.json"
    _make_fake_ffmpeg(bin_dir, log_path)
    clips = _make_clips(tmp_path)

    result = subprocess.run(
        [
            "bash",
            str(STITCH_SCRIPT),
            "--output-file",
            str(clips[0]),
            "--inputs",
            str(clips[0]),
            str(clips[1]),
        ],
        env=_env_with_bin(bin_dir),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert clips[0].read_bytes() == b"STITCHED_MP4_BYTES"


@pytest.mark.parametrize("ffmpeg_mode", ["fail", "empty"])
def test_ffmpeg_failure_or_empty_output_preserves_existing_file(tmp_path, ffmpeg_mode):
    bin_dir = tmp_path / "bin"
    log_path = tmp_path / "ffmpeg_log.json"
    _make_fake_ffmpeg(bin_dir, log_path, mode=ffmpeg_mode)
    clips = _make_clips(tmp_path)
    out_file = tmp_path / "existing.mp4"
    out_file.write_bytes(b"ORIGINAL_VIDEO")

    result = subprocess.run(
        [
            "bash",
            str(STITCH_SCRIPT),
            "--output-file",
            str(out_file),
            "--inputs",
            str(clips[0]),
            str(clips[1]),
        ],
        env=_env_with_bin(bin_dir),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert out_file.read_bytes() == b"ORIGINAL_VIDEO"
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".stitch-tmp.")]
    assert leftovers == []


@pytest.mark.parametrize(
    ("extra_args", "error_fragment"),
    [
        (["--mode", "invalid"], "unsupported --mode"),
        (["--mode", "copy", "--fps", "24"], "--fps is only supported with --mode normalize"),
        (["--fps", "0"], "--fps must be an integer between 1 and 120"),
        (["--fps", "121"], "--fps must be an integer between 1 and 120"),
        (["--fps", "abc"], "--fps must be an integer between 1 and 120"),
    ],
)
def test_rejects_invalid_options_before_creating_output_dir(tmp_path, extra_args, error_fragment):
    bin_dir = tmp_path / "bin"
    _make_fake_ffmpeg(bin_dir, tmp_path / "log.json")
    clips = _make_clips(tmp_path)
    out_dir = tmp_path / "never-created"
    out_file = out_dir / "out.mp4"

    result = subprocess.run(
        [
            "bash",
            str(STITCH_SCRIPT),
            "--output-file",
            str(out_file),
            "--inputs",
            str(clips[0]),
            str(clips[1]),
            *extra_args,
        ],
        env=_env_with_bin(bin_dir),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert error_fragment in result.stderr
    assert not out_dir.exists()


def test_rejects_bad_inputs_and_extensions_before_touching_output(tmp_path):
    bin_dir = tmp_path / "bin"
    _make_fake_ffmpeg(bin_dir, tmp_path / "log.json")
    clips = _make_clips(tmp_path)
    empty_clip = tmp_path / "empty.mp4"
    empty_clip.write_bytes(b"")
    out_dir = tmp_path / "untouched"

    cases = [
        (["--output-file", str(out_dir / "out.mp4"), "--inputs", str(clips[0])], "at least 2 video clips"),
        (["--output-file", str(out_dir / "out.webm"), "--inputs", str(clips[0]), str(clips[1])], "unsupported output extension"),
        (["--output-file", str(out_dir / "out.mp4"), "--inputs", str(clips[0]), str(tmp_path / "missing.mp4")], "input clip not found"),
        (["--output-file", str(out_dir / "out.mp4"), "--inputs", str(clips[0]), str(empty_clip)], "input clip is empty"),
        (["--output-file", str(tmp_path), "--inputs", str(clips[0]), str(clips[1])], "existing directory"),
    ]
    for argv, expected_err in cases:
        result = subprocess.run(
            ["bash", str(STITCH_SCRIPT), *argv],
            env=_env_with_bin(bin_dir),
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 1
        assert expected_err in result.stderr
        assert not out_dir.exists()


def test_reports_missing_ffmpeg_cleanly_without_creating_output_dir(tmp_path):
    clips = _make_clips(tmp_path)
    out_dir = tmp_path / "no-ffmpeg-out"

    # Build a minimal PATH containing core utilities needed before ffmpeg check,
    # explicitly excluding ffmpeg so this test stays deterministic even when
    # ffmpeg is installed globally in /usr/bin.
    minimal_bin = tmp_path / "minimal_bin"
    minimal_bin.mkdir()
    for tool in ("tr", "dirname", "basename", "mkdir", "mktemp", "rm", "rmdir", "mv"):
        resolved = shutil.which(tool)
        if resolved:
            os.symlink(resolved, minimal_bin / tool)

    bash_exe = shutil.which("bash") or "/bin/bash"
    env = {"PATH": str(minimal_bin)}
    result = subprocess.run(
        [
            bash_exe,
            str(STITCH_SCRIPT),
            "--output-file",
            str(out_dir / "out.mp4"),
            "--inputs",
            str(clips[0]),
            str(clips[1]),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "ffmpeg is required" in result.stderr
    assert not out_dir.exists()
