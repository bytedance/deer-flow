"""Media probe leg (spec 2026-09-08 §2, plan Task 3).

第一条腿：ffprobe 探测时长与可解码性。这是**硬失败腿**——文件不可解码/非视频/
探测超时都让文档 failed 并带可操作错误（对齐 worker 的 EmptyParseResultError
响亮失败纪律），绝不静默走到 ready。

时长（``duration_ms``）是整条管线的唯一主时钟（spec §3 时间轴对齐规则）：
segment / keyframe / caption / materialize 各腿的区间都落在这条 PTS 毫秒轴上。

ffprobe 是外部二进制，本机/CI 不保证可用：解析（``parse_ffprobe_json``）与
错误映射是纯逻辑，用 fake runner 全覆盖；真实二进制调用（``probe_video`` 默认
路径）经 ``run_file_io`` 落文件 IO 线程池包裹（blocking subprocess 不阻塞事件
循环，对齐 blocking-io-guard 纪律），worker 腿（Task 7）直接 await。
"""

from __future__ import annotations

import json
import logging
import subprocess
from collections.abc import Callable
from dataclasses import dataclass

from deerflow.utils.file_io import run_file_io

logger = logging.getLogger(__name__)

#: ffprobe 探测超时（秒）——超大/损坏文件的护栏。
_FFPROBE_TIMEOUT = 60.0

_FFPROBE_MISSING_MSG = "未找到 ffprobe 可执行文件：视频入库依赖 ffmpeg 工具链，请安装 ffmpeg（自带 ffprobe）并确保其在服务进程的 PATH 中"


class VideoProbeError(Exception):
    """probe 腿失败基类。"""


class FfprobeMissingError(VideoProbeError):
    """ffprobe 二进制不可用（环境问题，非文件问题）——可操作：安装 ffmpeg。"""


class VideoUndecodableError(VideoProbeError):
    """文件损坏/不可解码/无视频流/探测超时——文档 failed（响亮失败，spec §2）。"""


@dataclass(frozen=True, slots=True)
class VideoProbe:
    """一次 ffprobe 探测的结果；``duration_ms`` 是管线主时钟。"""

    duration_ms: int
    width: int
    height: int
    has_video_stream: bool
    has_audio_stream: bool


#: runner 契约：接收 ffprobe 命令行，返回 CompletedProcess（默认 subprocess.run）。
FfprobeRunner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


def _ffprobe_command(path: str) -> list[str]:
    return ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path]


def _default_runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=_FFPROBE_TIMEOUT)


def parse_ffprobe_json(raw: str) -> VideoProbe:
    """把 ffprobe 的 JSON 输出解析为 VideoProbe（纯函数，可单测）。

    响亮失败契约：坏 JSON / 缺 duration / duration<=0 / 无视频流都抛
    ``VideoUndecodableError``——绝不返回半残 probe 让下游瞎跑。
    """
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise VideoUndecodableError("文件不可解码为视频：ffprobe 输出不是合法 JSON（文件可能已损坏或非媒体文件）") from exc

    fmt = payload.get("format") or {}
    try:
        duration_ms = int(round(float(fmt.get("duration")) * 1000))
    except (TypeError, ValueError) as exc:
        raise VideoUndecodableError("文件不可解码为视频：ffprobe 未报告有效时长（format.duration 缺失或非数值）") from exc
    if duration_ms <= 0:
        raise VideoUndecodableError(f"文件不可解码为视频：时长非正（{duration_ms} ms），可能是空文件或损坏容器")

    streams = payload.get("streams") or []
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    if video is None:
        raise VideoUndecodableError("文件不含视频流：无法作为视频入库（若是纯音频请改走音频转写路径）")
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)

    return VideoProbe(
        duration_ms=duration_ms,
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        has_video_stream=True,
        has_audio_stream=audio is not None,
    )


async def probe_video(path: str, *, runner: FfprobeRunner | None = None) -> VideoProbe:
    """探测视频文件的时长与可解码性（第一条腿，硬失败）。

    blocking 的 subprocess 调用经 ``run_file_io`` 落文件 IO 线程池，不阻塞事件
    循环。``runner`` 可注入（测试用 fake，无需真实 ffprobe）；默认走 subprocess。
    """
    run = runner or _default_runner
    cmd = _ffprobe_command(path)

    def _blocking() -> str:
        try:
            proc = run(cmd)
        except FileNotFoundError as exc:
            raise FfprobeMissingError(_FFPROBE_MISSING_MSG) from exc
        except subprocess.TimeoutExpired as exc:
            raise VideoUndecodableError(f"文件探测超时（>{_FFPROBE_TIMEOUT:.0f}s）：文件可能过大或已损坏") from exc
        if proc.returncode != 0:
            detail = (proc.stderr or "").strip()
            raise VideoUndecodableError(f"文件不可解码为视频：{detail or 'ffprobe 返回非零退出码'}")
        return proc.stdout or ""

    raw = await run_file_io(_blocking)
    return parse_ffprobe_json(raw)
