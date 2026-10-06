"""Keyframe extraction leg tests (spec 2026-09-08 §2/§8, plan Task 5).

ffmpeg 是外部二进制（本机/CI 不装），故抽帧的纯逻辑——帧路径格式、中帧计算、
缩放预算、命令构造、缺帧 None 降级——用 fake runner 全覆盖；真实抽帧端到端
标 skipif。

关键降级契约（spec §2）：单镜头抽帧失败返回 None（引用不带 frame_url），绝不
阻断其他镜头；持久化帧落 doc_dir/frames/（对齐 images/ 先例，删除文档级联删）；
caption 临时帧走 stdout pipe、**不持久化**。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from deerflow.knowledge.video.frames import (
    extract_caption_frames,
    extract_keyframes,
    ffmpeg_frame_command,
    frame_relative_path,
    mid_point_ms,
    scale_filter,
)

# ── 纯函数：路径/中帧/缩放/命令 ───────────────────────────────────────────


def test_frame_relative_path_format():
    """帧相对 doc_dir 的路径：frames/shot_%04d.jpg（doc_id 已在 doc_dir，不再嵌套）。"""
    assert frame_relative_path(0) == "frames/shot_0000.jpg"
    assert frame_relative_path(12) == "frames/shot_0012.jpg"


def test_mid_point_ms():
    assert mid_point_ms(0, 5000) == 2500
    assert mid_point_ms(1000, 2000) == 1500
    assert mid_point_ms(0, 1) == 0  # 整数除，短镜头中帧取整


def test_scale_filter_caps_long_edge_without_upscaling():
    f = scale_filter(1280)
    assert "1280" in f
    assert "force_original_aspect_ratio=decrease" in f  # 只缩不放，保持宽高比


def test_ffmpeg_frame_command_structure():
    cmd = ffmpeg_frame_command("/v/clip.mp4", 2500, "/out/shot_0000.jpg", max_px=1280, quality=5)
    assert cmd[0] == "ffmpeg"
    assert cmd[cmd.index("-ss") + 1] == "2.500"  # at_ms/1000 → 秒，三位小数
    assert cmd[cmd.index("-i") + 1] == "/v/clip.mp4"
    assert cmd[cmd.index("-frames:v") + 1] == "1"  # 单帧
    assert "-vf" in cmd
    assert cmd[-1] == "/out/shot_0000.jpg"


def test_ffmpeg_frame_command_pipe_output_uses_image2pipe():
    """caption 临时帧输出到 stdout（pipe:1）时需声明 image2pipe 格式。"""
    cmd = ffmpeg_frame_command("/v.mp4", 1000, "pipe:1")
    assert cmd[cmd.index("-f") + 1] == "image2pipe"
    assert cmd[-1] == "pipe:1"


# ── extract_keyframes：fake runner 编排 ──────────────────────────────────


class _FakeRunner:
    """模拟 ffmpeg：成功则在 out_path 落 JPEG magic，失败则非零退出且不落盘。"""

    def __init__(self, fail_substrings=()):
        self.fail_substrings = fail_substrings
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess:
        self.calls.append(cmd)
        out = cmd[-1]
        if any(sub in out for sub in self.fail_substrings):
            return subprocess.CompletedProcess(cmd, 1, "", "boom")
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(b"\xff\xd8\xff\xe0")  # JPEG magic
        return subprocess.CompletedProcess(cmd, 0, "", "")


async def test_extract_keyframes_persists_and_returns_rel_paths(tmp_path):
    doc_dir = tmp_path / "knowledge" / "kb1" / "doc1"
    doc_dir.mkdir(parents=True)
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"placeholder")
    runner = _FakeRunner()

    result = await extract_keyframes(str(video), [(0, 5000), (5000, 12000)], str(doc_dir), runner=runner)

    assert result == {0: "frames/shot_0000.jpg", 1: "frames/shot_0001.jpg"}
    assert (doc_dir / "frames" / "shot_0000.jpg").exists()  # 落 doc_dir/frames/
    assert (doc_dir / "frames" / "shot_0001.jpg").exists()
    assert len(runner.calls) == 2


async def test_extract_keyframes_single_failure_returns_none(tmp_path):
    """单镜头抽帧失败 → None，不阻断其他镜头（spec §2 降级）。"""
    doc_dir = tmp_path / "doc1"
    doc_dir.mkdir(parents=True)
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"placeholder")
    runner = _FakeRunner(fail_substrings=("shot_0001",))

    result = await extract_keyframes(str(video), [(0, 5000), (5000, 12000)], str(doc_dir), runner=runner)

    assert result[0] == "frames/shot_0000.jpg"
    assert result[1] is None


async def test_extract_keyframes_empty_shots_is_empty_dict(tmp_path):
    assert await extract_keyframes("clip.mp4", [], str(tmp_path)) == {}


async def test_extract_caption_frames_returns_bytes_not_persisted(tmp_path):
    """caption 临时帧走 stdout pipe、返回内存 bytes、不落盘（spec §2 至多 3 帧）。"""
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"placeholder")

    class _PipeRunner:
        def __init__(self):
            self.calls: list[list[str]] = []

        def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess:
            self.calls.append(cmd)
            assert cmd[-1] == "pipe:1"  # 输出到 stdout，非文件
            return subprocess.CompletedProcess(cmd, 0, b"\xff\xd8\xff\xe0jpeg", "")

    runner = _PipeRunner()
    frames = await extract_caption_frames(str(video), 0, 9000, count=3, runner=runner)

    assert frames == [b"\xff\xd8\xff\xe0jpeg"] * 3
    assert len(runner.calls) == 3
    assert not list(tmp_path.rglob("*.jpg"))  # 未持久化任何帧文件


# ── 真实 ffmpeg 端到端（仅在 ffmpeg 可用时跑）────────────────────────────

_HAS_FFMPEG = shutil.which("ffmpeg") is not None


@pytest.mark.skipif(not _HAS_FFMPEG, reason="ffmpeg not installed on this host")
async def test_extract_keyframes_real_ffmpeg_produces_jpeg(tmp_path):
    doc_dir = tmp_path / "doc1"
    doc_dir.mkdir(parents=True)
    clip = tmp_path / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=1920x1080:d=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)],
        check=True,
        capture_output=True,
    )

    result = await extract_keyframes(str(clip), [(0, 3000)], str(doc_dir))

    frame = doc_dir / "frames" / "shot_0000.jpg"
    assert result == {0: "frames/shot_0000.jpg"}
    assert frame.exists() and frame.read_bytes()[:2] == b"\xff\xd8"  # JPEG magic
