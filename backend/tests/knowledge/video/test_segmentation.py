"""Scene segmentation pure-function tests (spec 2026-09-08 §2/§3, plan Task 4).

segment 腿的纯逻辑核心：把场景检测器的毫秒切点合并成铺满 PTS 轴的镜头区间，
施加 max_shot 兜底必切；检测器失败时退化等距回退窗。**不依赖 PySceneDetect**
（检测器封在 worker 腿内、可 fake），故本测试全本机可跑、无 skipif。

钉死的关键不变量（spec §3 时间轴对齐规则的主时钟）：产出镜头序列必须
①首段起于 0、末段止于 duration_ms ②相邻无缝无重叠 ③按 start_ms 升序
（= shot_index 序 = chunk_index 序）④每段 ≤ max_shot_ms ⑤同输入恒同输出。
"""

from __future__ import annotations

from deerflow.knowledge.video.segmentation import fallback_windows, merge_scene_bounds


def _assert_seamless_coverage(bounds: list[tuple[int, int]], duration_ms: int) -> None:
    """镜头序列必须无缝铺满 [0, duration_ms]、升序、无零长度段。"""
    assert bounds, "非正时长以外必须产出至少一个镜头"
    assert bounds[0][0] == 0, "首段起于 0"
    assert bounds[-1][1] == duration_ms, "末段止于 duration_ms"
    for (s1, e1), (s2, e2) in zip(bounds, bounds[1:], strict=False):
        assert e1 == s2, "相邻镜头无缝、无重叠"
        assert s1 < e1, "无零长度镜头"
        assert s2 < e2, "升序且无零长度"


# ── merge_scene_bounds：兜底必切 ──────────────────────────────────────────


def test_merge_no_cuts_force_splits_long_video():
    """无视觉切点（固定机位讲课/录屏）→ 按 max_shot 上界等分兜底切。"""
    assert merge_scene_bounds([], duration_ms=12000, max_shot_ms=5000) == [(0, 4000), (4000, 8000), (8000, 12000)]


def test_merge_respects_cuts_within_max():
    """切点分出的镜头都 ≤ max_shot → 原样保留，不兜底切。"""
    assert merge_scene_bounds([3000, 7000], duration_ms=10000, max_shot_ms=5000) == [(0, 3000), (3000, 7000), (7000, 10000)]


def test_merge_force_splits_only_the_long_span():
    """只对超过 max_shot 的镜头兜底切，短镜头原样。"""
    # (0,15000) 长 15000 > 5000 → 等分 3 段；(15000,20000) 长 5000 → 保留
    assert merge_scene_bounds([15000], duration_ms=20000, max_shot_ms=5000) == [(0, 5000), (5000, 10000), (10000, 15000), (15000, 20000)]


def test_merge_exact_max_shot_span_is_not_split():
    """镜头长度恰等于 max_shot → 不切（上界是 ≤ 而非 <）。"""
    assert merge_scene_bounds([], duration_ms=10000, max_shot_ms=5000) == [(0, 5000), (5000, 10000)]


# ── merge_scene_bounds：切点规整（去重/排序/裁剪/取整）────────────────────


def test_merge_dedupes_and_sorts_cuts():
    """重复 + 乱序切点 → 去重升序（max_shot 设大以隔离兜底，仅验规整）。"""
    assert merge_scene_bounds([7000, 3000, 3000, 7000], duration_ms=10000, max_shot_ms=20000) == [(0, 3000), (3000, 7000), (7000, 10000)]


def test_merge_clamps_out_of_range_cuts():
    """越界/与端点重合的切点丢弃：只保留开区间 (0, duration_ms) 内的内部切点。"""
    assert merge_scene_bounds([-500, 0, 5000, 10000, 15000], duration_ms=10000, max_shot_ms=20000) == [(0, 5000), (5000, 10000)]


def test_merge_coerces_float_cuts_to_integer_ms():
    """切点 round 到整数毫秒（worker 从 FrameTimecode 转换可能带浮点）。"""
    assert merge_scene_bounds([3000.6, 7000.2], duration_ms=10000, max_shot_ms=20000) == [(0, 3001), (3001, 7000), (7000, 10000)]


def test_merge_drops_duplicate_cuts_at_same_position():
    """同一位置的重复切点不产生零长度镜头。"""
    bounds = merge_scene_bounds([5000, 5000, 5000], duration_ms=10000, max_shot_ms=20000)
    assert bounds == [(0, 5000), (5000, 10000)]
    assert all(start < end for start, end in bounds)  # 无零长度


# ── merge_scene_bounds：边界与降级输入 ────────────────────────────────────


def test_merge_empty_on_non_positive_duration():
    assert merge_scene_bounds([3000], duration_ms=0, max_shot_ms=5000) == []
    assert merge_scene_bounds([3000], duration_ms=-100, max_shot_ms=5000) == []


def test_merge_non_positive_max_shot_disables_forced_cut():
    """max_shot<=0 视为无上界，不兜底切（config 层已保证 >0，此处为纯函数健壮性）。"""
    assert merge_scene_bounds([], duration_ms=12000, max_shot_ms=0) == [(0, 12000)]


def test_merge_single_short_shot_when_duration_below_max():
    """整片短于 max_shot → 单镜头。"""
    assert merge_scene_bounds([], duration_ms=3000, max_shot_ms=5000) == [(0, 3000)]


# ── merge_scene_bounds：不变量 ────────────────────────────────────────────


def test_merge_covers_timeline_seamlessly():
    bounds = merge_scene_bounds([2500, 9000, 15000], duration_ms=17000, max_shot_ms=4000)
    _assert_seamless_coverage(bounds, 17000)


def test_merge_every_span_within_max_shot():
    """兜底切后每段长度 ≤ max_shot_ms（粒度上界，spec §3）。"""
    bounds = merge_scene_bounds([1000, 13000], duration_ms=20000, max_shot_ms=3000)
    assert all(end - start <= 3000 for start, end in bounds)
    _assert_seamless_coverage(bounds, 20000)


def test_merge_is_deterministic_across_calls_and_input_order():
    """同输入两次调用恒等；乱序输入 == 排序输入（确定性，可 resume/复跑）。"""
    first = merge_scene_bounds([7000, 3000, 15000], duration_ms=20000, max_shot_ms=4000)
    second = merge_scene_bounds([7000, 3000, 15000], duration_ms=20000, max_shot_ms=4000)
    shuffled = merge_scene_bounds([15000, 7000, 3000], duration_ms=20000, max_shot_ms=4000)
    assert first == second
    assert first == shuffled


# ── fallback_windows：等距回退窗（segment 腿失败降级）─────────────────────


def test_fallback_even_windows_with_short_tail():
    assert fallback_windows(duration_ms=25000, window_ms=10000) == [(0, 10000), (10000, 20000), (20000, 25000)]


def test_fallback_single_window_when_shorter_than_window():
    assert fallback_windows(duration_ms=5000, window_ms=10000) == [(0, 5000)]


def test_fallback_exact_multiple_has_no_zero_tail():
    """时长恰为窗口整数倍 → 末窗不产生零长度段。"""
    assert fallback_windows(duration_ms=20000, window_ms=10000) == [(0, 10000), (10000, 20000)]


def test_fallback_empty_on_non_positive_inputs():
    assert fallback_windows(duration_ms=0, window_ms=10000) == []
    assert fallback_windows(duration_ms=-1, window_ms=10000) == []
    assert fallback_windows(duration_ms=25000, window_ms=0) == []


def test_fallback_covers_timeline_seamlessly():
    _assert_seamless_coverage(fallback_windows(duration_ms=23456, window_ms=10000), 23456)


def test_fallback_is_deterministic():
    assert fallback_windows(duration_ms=25000, window_ms=10000) == fallback_windows(duration_ms=25000, window_ms=10000)
