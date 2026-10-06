"""Scene segmentation pure functions (spec 2026-09-08 §2/§3, plan Task 4).

第三条腿（segment）的纯逻辑核心：把场景检测器（PySceneDetect ContentDetector，
封在 worker 腿内、可 fake）产出的毫秒切点，合并成铺满 PTS 轴的镜头区间序列，
并施加 ``max_shot`` 兜底必切；检测器整腿失败时退化为等距回退窗（segment=degraded）。

**不依赖 PySceneDetect**——检测器只是切点的一个来源，换成 TransNetV2 只改 worker
腿内一行（spec §3 决策），本模块只吃「毫秒切点列表」这一稳定契约，故全本机可测。

镜头边界即镜头卡的时间桶边界（spec §3 时间轴对齐规则的主时钟）：产出序列必须
①首段起于 0、末段止于 ``duration_ms`` ②相邻无缝无重叠 ③按 start_ms 升序
（= shot_index 序 = chunk_index 序）④每段 ≤ ``max_shot_ms`` ⑤同输入恒同输出。
这些不变量由 test_segmentation.py 逐条钉死。
"""

from __future__ import annotations

from collections.abc import Iterable

#: 一个镜头区间 ``[start_ms, end_ms)`` —— PTS 毫秒轴上的闭开区间。
ShotBound = tuple[int, int]


def _split_long_span(start: int, end: int, max_shot_ms: int) -> list[ShotBound]:
    """把超过 ``max_shot_ms`` 的长镜头等分成 n 段（n = ceil(len/max)），整数边界无缝。

    等分（而非固定步长）避免末尾碎片：每段 ≈ len/n ≤ max_shot_ms，粒度均匀。
    整数除法 ``start + (length * i) // n`` 保证边界单调、无缝、末段精确止于 end。
    """
    length = end - start
    if length <= max_shot_ms:
        return [(start, end)]
    n = -(-length // max_shot_ms)  # ceil division
    bounds = [start + (length * i) // n for i in range(n + 1)]
    return [(bounds[i], bounds[i + 1]) for i in range(n)]


def merge_scene_bounds(cuts: Iterable[float], duration_ms: int, max_shot_ms: int) -> list[ShotBound]:
    """把场景切点合并为铺满 ``[0, duration_ms]`` 的镜头区间序列，长镜头兜底必切。

    纯函数，segment 腿主路径：

    - 规整 cuts：round 到整数毫秒、去重、升序、裁剪到开区间 ``(0, duration_ms)``
      （``<=0`` 或 ``>=duration_ms`` 的切点与端点重合或越界，是边界非内部切点，丢弃）；
    - 边界链 = ``[0] + 规整 cuts + [duration_ms]``，相邻边界成初始镜头；
    - 兜底必切：任何 ``> max_shot_ms`` 的镜头等分至每段 ``<= max_shot_ms``
      （``max_shot_ms<=0`` 视为无上界、不兜底——config 层 RagVideoConfig 已保证 >0，
      此分支仅为纯函数健壮性）；
    - 零长度镜头（``start==end``）剔除；
    - 确定性：同输入（含乱序/重复/浮点）恒同输出，可 resume/复跑。

    ``duration_ms<=0`` → ``[]``（无有效时间轴）。
    """
    if duration_ms <= 0:
        return []
    rounded = [int(round(cut)) for cut in cuts]
    inner = sorted({cut for cut in rounded if 0 < cut < duration_ms})
    bounds = [0, *inner, duration_ms]
    shots: list[ShotBound] = []
    for start, end in zip(bounds, bounds[1:], strict=False):
        if end <= start:
            continue  # 零长度防御（规整后一般不出现）
        if max_shot_ms > 0:
            shots.extend(_split_long_span(start, end, max_shot_ms))
        else:
            shots.append((start, end))
    return shots


def fallback_windows(duration_ms: int, window_ms: int) -> list[ShotBound]:
    """segment 腿失败时的等距回退窗（spec §2 降级：segment=degraded）。

    从 0 起每 ``window_ms`` 一窗，末窗止于 ``duration_ms``（可能短于 window_ms）；
    同样满足无缝覆盖 / 升序 / 无零长度不变量。``duration_ms<=0`` 或
    ``window_ms<=0`` → ``[]``。
    """
    if duration_ms <= 0 or window_ms <= 0:
        return []
    windows: list[ShotBound] = []
    start = 0
    while start < duration_ms:
        end = min(start + window_ms, duration_ms)
        windows.append((start, end))
        start = end
    return windows
