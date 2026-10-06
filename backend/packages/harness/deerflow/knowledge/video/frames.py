"""Keyframe extraction leg (spec 2026-09-08 §2/§8, plan Task 5).

第四条腿（keyframe）的执行层：每镜头取中帧持久化为 JPEG（q80 预算、长边
≤1280px），落 ``doc_dir/frames/shot_%04d.jpg``——对齐现有 ``images/`` 布局
（``doc_dir`` 已是 per-doc 目录 ``data_dir/knowledge/{kb_id}/{doc_id}``，故不再
嵌套 doc_id）；删除文档时 ``_remove_dir(doc_dir)`` 自动级联删帧（spec §9 存储
膨胀缓解）。keyframe_path 存相对 doc_dir 的路径（对齐 ParsedImage.ref）。

降级契约（spec §2）：单镜头抽帧失败 → 该镜头 ``keyframe_path=None``（引用不带
frame_url），绝不阻断其他镜头；>30% 失败由调用方（worker Task 7）标腿 degraded。

caption 临时帧（≤3 帧）走 stdout pipe、只返回内存 bytes、**不持久化**（spec §2），
供 Task 6 的 VLM captioner 消费。

ffmpeg 是外部二进制：命令构造/路径/缩放是纯逻辑（fake runner 全覆盖），真实
抽帧经 ``run_file_io`` 落线程池（blocking subprocess 不阻塞事件循环）。
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from deerflow.utils.file_io import run_file_io

logger = logging.getLogger(__name__)

#: JPEG 质量预算（spec §8「q80」）映射到 ffmpeg mjpeg ``-q:v``（1 最好，31 最差）；
#: 5 ≈ JPEG q80 的视觉质量档，实测校准时可调。
_JPEG_QV = 5
#: 长边像素上界（spec §8「≤1280px」）。
_MAX_PX = 1280
#: ffmpeg 抽帧超时（秒）。
_FRAME_TIMEOUT = 60.0

#: runner 契约：接收 ffmpeg 命令行，返回 CompletedProcess（stdout 为 bytes，caption 帧走 pipe）。
FrameRunner = Callable[[list[str]], "subprocess.CompletedProcess[bytes]"]


def frame_relative_path(shot_index: int) -> str:
    """帧相对 ``doc_dir`` 的路径：``frames/shot_%04d.jpg``（存 ``video_shots.keyframe_path``）。"""
    return f"frames/shot_{shot_index:04d}.jpg"


def mid_point_ms(start_ms: int, end_ms: int) -> int:
    """镜头中帧时间点（PTS 毫秒轴）——中帧最能代表镜头内容（spec §2 每镜头取中帧）。"""
    return (start_ms + end_ms) // 2


def scale_filter(max_px: int = _MAX_PX) -> str:
    """ffmpeg 缩放 filter：长边 ≤ ``max_px``、保持宽高比、**不放大**小帧。"""
    return f"scale={max_px}:{max_px}:force_original_aspect_ratio=decrease"


def ffmpeg_frame_command(video_path: str, at_ms: int, out: str, *, max_px: int = _MAX_PX, quality: int = _JPEG_QV) -> list[str]:
    """抽单帧命令。``out`` 为文件路径时落盘；为 ``pipe:1`` 时输出 JPEG 到 stdout
    （caption 临时帧用，需声明 image2pipe 格式）。``-ss`` 前置做快速 seek。"""
    cmd = ["ffmpeg", "-y", "-ss", f"{at_ms / 1000:.3f}", "-i", video_path, "-frames:v", "1", "-vf", scale_filter(max_px), "-q:v", str(quality)]
    if out in ("pipe:1", "-"):
        cmd += ["-f", "image2pipe"]
    cmd.append(out)
    return cmd


def _default_runner(cmd: list[str]) -> subprocess.CompletedProcess[bytes]:
    # capture_output 无 text=True → stdout 为 bytes（caption 帧走 pipe 需二进制 JPEG）
    return subprocess.run(cmd, capture_output=True, timeout=_FRAME_TIMEOUT)


async def extract_keyframes(
    video_path: str,
    shots: Sequence[tuple[int, int]],
    doc_dir: str,
    *,
    runner: FrameRunner | None = None,
    max_px: int = _MAX_PX,
    quality: int = _JPEG_QV,
) -> dict[int, str | None]:
    """每镜头抽中帧持久化到 ``doc_dir/frames/``；返回 ``{shot_index: rel_path | None}``。

    ``shots[i] = (start_ms, end_ms)``（对齐 segmentation 产出序），``shot_index = i``。
    单镜头失败（ffmpeg 非零退出 / 未落盘 / 异常）→ None，不阻断其他镜头。整个抽帧
    循环一次 ``run_file_io`` 落线程池（抽帧快，``-ss`` 前置 seek）。
    """
    if not shots:
        return {}
    run = runner or _default_runner
    base = Path(doc_dir)

    def _blocking() -> dict[int, str | None]:
        results: dict[int, str | None] = {}
        (base / "frames").mkdir(parents=True, exist_ok=True)
        for index, (start_ms, end_ms) in enumerate(shots):
            rel = frame_relative_path(index)
            out = base / rel
            cmd = ffmpeg_frame_command(video_path, mid_point_ms(start_ms, end_ms), str(out), max_px=max_px, quality=quality)
            try:
                proc = run(cmd)
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
                logger.warning("keyframe extraction failed for shot %d (%s); degrading to no frame", index, exc)
                results[index] = None
                continue
            if proc.returncode == 0 and out.exists() and out.stat().st_size > 0:
                results[index] = rel
            else:
                logger.warning("keyframe extraction produced no frame for shot %d (rc=%s); degrading", index, proc.returncode)
                results[index] = None
        return results

    return await run_file_io(_blocking)


async def extract_caption_frames(
    video_path: str,
    start_ms: int,
    end_ms: int,
    *,
    count: int = 3,
    runner: FrameRunner | None = None,
    max_px: int = _MAX_PX,
    quality: int = _JPEG_QV,
) -> list[bytes]:
    """caption 临时帧：镜头区间内均匀采 ≤``count`` 帧，走 stdout pipe 返回内存 bytes，
    **不持久化**（spec §2 caption 临时可用至多 3 帧）。单帧失败跳过（返回已成功的
    部分）；采样点取 count 等分的中心（避免首尾黑帧）；供 Task 6 VLM captioner 消费。
    """
    if count <= 0 or end_ms <= start_ms:
        return []
    run = runner or _default_runner
    span = end_ms - start_ms
    points = [start_ms + span * (2 * i + 1) // (2 * count) for i in range(count)]

    def _blocking() -> list[bytes]:
        frames: list[bytes] = []
        for at_ms in points:
            cmd = ffmpeg_frame_command(video_path, at_ms, "pipe:1", max_px=max_px, quality=quality)
            try:
                proc = run(cmd)
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
                logger.warning("caption frame extraction failed at %dms (%s); skipping", at_ms, exc)
                continue
            if proc.returncode == 0 and proc.stdout:
                frames.append(proc.stdout)
        return frames

    return await run_file_io(_blocking)
