"""probe leg contract tests (spec 2026-09-08 §2, plan Task 3).

ffprobe 是外部二进制：本机/CI 不保证可用，故核心契约（JSON 解析、可解码性
判定、错误映射、编排）用 fake runner + 真实 JSON 字符串全覆盖；真实二进制
端到端仅在 ffprobe/ffmpeg 可用时跑（skipif），不阻塞纯逻辑回归。

probe 是硬失败腿：不可解码 → 文档 failed + 可操作错误（对齐 worker 的
EmptyParseResultError 响亮失败纪律，spec §2）。
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from deerflow.knowledge.video.probe import (
    FfprobeMissingError,
    VideoProbe,
    VideoUndecodableError,
    parse_ffprobe_json,
    probe_video,
)

_VALID_JSON = json.dumps(
    {
        "format": {"duration": "2.035000", "format_name": "mov,mp4,m4a,3gp,3g2,mj2"},
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "width": 1280, "height": 720},
            {"codec_type": "audio", "codec_name": "aac", "sample_rate": "44100"},
        ],
    }
)


def _completed(stdout: str, returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["ffprobe"], returncode=returncode, stdout=stdout, stderr=stderr)


# ── parse_ffprobe_json 纯函数 ────────────────────────────────────────────


def test_parse_extracts_duration_and_streams():
    probe = parse_ffprobe_json(_VALID_JSON)
    assert probe == VideoProbe(duration_ms=2035, width=1280, height=720, has_video_stream=True, has_audio_stream=True)


def test_parse_rounds_subsecond_duration_to_ms():
    raw = json.dumps({"format": {"duration": "0.9999"}, "streams": [{"codec_type": "video", "width": 64, "height": 64}]})
    assert parse_ffprobe_json(raw).duration_ms == 1000


def test_parse_rejects_malformed_json():
    with pytest.raises(VideoUndecodableError):
        parse_ffprobe_json("this is not json at all")


def test_parse_rejects_missing_duration():
    raw = json.dumps({"format": {}, "streams": [{"codec_type": "video", "width": 64, "height": 64}]})
    with pytest.raises(VideoUndecodableError):
        parse_ffprobe_json(raw)


def test_parse_rejects_audio_only_container():
    """无视频流（音频文件改后缀伪装 .mp4）→ 不可解码为视频，响亮失败。"""
    raw = json.dumps({"format": {"duration": "3.0"}, "streams": [{"codec_type": "audio", "codec_name": "mp3"}]})
    with pytest.raises(VideoUndecodableError):
        parse_ffprobe_json(raw)


def test_parse_rejects_zero_duration():
    raw = json.dumps({"format": {"duration": "0.0"}, "streams": [{"codec_type": "video", "width": 64, "height": 64}]})
    with pytest.raises(VideoUndecodableError):
        parse_ffprobe_json(raw)


# ── probe_video 编排（fake runner，无需真实 ffprobe）─────────────────────


async def test_probe_video_happy_path_invokes_ffprobe_on_path(tmp_path):
    seen: list[list[str]] = []

    def runner(cmd: list[str]) -> subprocess.CompletedProcess:
        seen.append(cmd)
        return _completed(_VALID_JSON)

    target = tmp_path / "clip.mp4"
    target.write_bytes(b"placeholder")

    probe = await probe_video(str(target), runner=runner)

    assert probe.duration_ms == 2035
    assert probe.has_audio_stream is True
    assert seen and seen[0][0] == "ffprobe" and seen[0][-1] == str(target)


async def test_probe_video_nonzero_exit_is_undecodable_with_stderr(tmp_path):
    def runner(cmd: list[str]) -> subprocess.CompletedProcess:
        return _completed("", returncode=1, stderr="Invalid data found when processing input")

    with pytest.raises(VideoUndecodableError) as excinfo:
        await probe_video(str(tmp_path / "bad.mp4"), runner=runner)

    assert "Invalid data" in str(excinfo.value)  # stderr 进可操作错误信息


async def test_probe_video_missing_binary_raises_ffprobe_missing(tmp_path):
    def runner(cmd: list[str]) -> subprocess.CompletedProcess:
        raise FileNotFoundError(2, "No such file or directory: 'ffprobe'")

    with pytest.raises(FfprobeMissingError):
        await probe_video(str(tmp_path / "clip.mp4"), runner=runner)


async def test_probe_video_timeout_is_undecodable(tmp_path):
    def runner(cmd: list[str]) -> subprocess.CompletedProcess:
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=30)

    with pytest.raises(VideoUndecodableError):
        await probe_video(str(tmp_path / "clip.mp4"), runner=runner)


# ── 真实二进制端到端（仅在 ffmpeg+ffprobe 可用时跑）──────────────────────

_HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


@pytest.mark.skipif(not _HAS_FFMPEG, reason="ffmpeg/ffprobe not installed on this host")
async def test_probe_video_real_synthesized_clip(tmp_path):
    clip = tmp_path / "silence.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x240:d=2",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=mono",
            "-t",
            "2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(clip),
        ],
        check=True,
        capture_output=True,
    )

    probe = await probe_video(str(clip))

    assert 1800 <= probe.duration_ms <= 2300  # ≈2s，留容器封装余量
    assert probe.has_video_stream and probe.width == 320 and probe.height == 240
