import asyncio
import json
import math
import sys
from pathlib import Path
from typing import Any

# 添加 features-tool 到 sys.path（ins 模块 + tools 包）
_FEATURES_TOOL_ROOT = Path(__file__).resolve().parent.parent
if str(_FEATURES_TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(_FEATURES_TOOL_ROOT))

from agents import function_tool
from pydantic import BaseModel, Field
from tools.get_orbit_data_tool import _get_orbit_data_impl


COORDINATE_SCALE_TO_UM = 1000.0


class OrbitCenterlineFeatureDetail(BaseModel):
    # 原始轨迹（多周期）特征
    raw_envelope_area: float | None = Field(default=None, description="包络面积，坐标缩放到 μm 后计算，单位 μm²")
    raw_repetition_score: float | None = Field(default=None, description="重复性得分，综合形状与大小相似性")
    raw_cycle_shape_similarity: float | None = Field(default=None, description="周期间形状相似性得分")
    raw_cycle_size_similarity: float | None = Field(default=None, description="周期间大小相似性得分")

    # 1X 轨迹（单周期）特征
    one_x_precession_direction: str | None = Field(default=None, description="进动方向，如 正进动/反进动")

    # 轨迹形状特征，基于原始轨迹的第一周期轨迹计算
    first_cycle_concavity_score: float | None = Field(default=None, description="凸凹程度得分，越高表示凹陷越明显")
    first_cycle_straight_transition_score: float | None = Field(default=None, description="直线过渡程度得分")
    first_cycle_figure_eight_score: float | None = Field(default=None, description=" 8 字形得分")
    first_cycle_crescent_score: float | None = Field(default=None, description="月牙形得分")
    first_cycle_orbit_area: float | None = Field(default=None, description="面积，单位 μm²")

    first_cycle_major_axis_length: float | None = Field(default=None, description="长轴长度，单位 μm")
    first_cycle_minor_axis_length: float | None = Field(default=None, description="短轴长度，单位 μm")
    first_cycle_axis_ratio: float | None = Field(default=None, description="长轴/短轴比")
    first_cycle_roundness_score: float | None = Field(default=None, description="近圆程度，越接近 1 越圆")
    first_cycle_ellipse_fit_residual: float | None = Field(default=None, description="椭圆拟合残差，越小越接近标准椭圆")
    first_cycle_self_intersection_count: int = Field(default=0, description="自交次数")
    first_cycle_radius_cv: float | None = Field(default=None, description="半径变异系数，越小越接近圆形")
    first_cycle_circle_likeness_score: float | None = Field(default=None, description="圆形相似度得分")
    first_cycle_ellipse_likeness_score: float | None = Field(default=None, description="椭圆形相似度得分")
    first_cycle_shape_label: str | None = Field(default=None, description="基于负面筛选与正向判别得到的形状标签，如 圆形/椭圆形")


class OrbitCenterlineAnalysisResult(BaseModel):
    machine_id: str = Field(description="机组 ID")
    bearing_id: str = Field(description="轴承 ID，应为 type_num/type_enum=70 的轴承")
    time_ms: str = Field(description="查询时间点，毫秒时间戳")

    summary: list[str] = Field(description="轴心轨迹整体概括")
    text_features: list[str] = Field(description="文本化特征")

    feature_details: OrbitCenterlineFeatureDetail = Field(description="提取出的原始轨迹/1X/原始轨迹第一周期结构化特征")

    probe_ids: list[str] = Field(default_factory=list, description="实际参与轨迹计算的探头 ID")
    cycle_count: int | None = Field(default=None, description="输入的周期数")


def _round_float(value: float | None, digits: int = 6) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _safe_mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _safe_std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean_v = _safe_mean(values)
    if mean_v is None:
        return 0.0
    return math.sqrt(sum((v - mean_v) ** 2 for v in values) / len(values))


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _extract_xy(points: Any) -> list[tuple[float, float]]:
    result: list[tuple[float, float]] = []
    if not isinstance(points, list):
        return result

    for item in points:
        if (
            isinstance(item, (list, tuple))
            and len(item) >= 2
            and isinstance(item[0], (int, float))
            and isinstance(item[1], (int, float))
            and math.isfinite(item[0])
            and math.isfinite(item[1])
        ):
            result.append((float(item[0]) * COORDINATE_SCALE_TO_UM, float(item[1]) * COORDINATE_SCALE_TO_UM))
            continue

        if isinstance(item, dict):
            x = item.get("x")
            y = item.get("y")
            if isinstance(x, (int, float)) and isinstance(y, (int, float)) and math.isfinite(x) and math.isfinite(y):
                result.append((float(x) * COORDINATE_SCALE_TO_UM, float(y) * COORDINATE_SCALE_TO_UM))
    return result


def _bbox_metrics(points: list[tuple[float, float]]) -> dict[str, float | None]:
    if not points:
        return {"x_min": None, "x_max": None, "y_min": None, "y_max": None, "width": None, "height": None}

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    return {
        "x_min": x_min,
        "x_max": x_max,
        "y_min": y_min,
        "y_max": y_max,
        "width": x_max - x_min,
        "height": y_max - y_min,
    }


def _center_metrics(points: list[tuple[float, float]]) -> dict[str, float | None]:
    if not points:
        return {"center_x": None, "center_y": None, "center_offset_radius": None}

    cx = _safe_mean([p[0] for p in points])
    cy = _safe_mean([p[1] for p in points])
    if cx is None or cy is None:
        return {"center_x": None, "center_y": None, "center_offset_radius": None}

    return {
        "center_x": cx,
        "center_y": cy,
        "center_offset_radius": math.sqrt(cx * cx + cy * cy),
    }


def _principal_axis_metrics(points: list[tuple[float, float]]) -> dict[str, float | None]:
    if len(points) < 3:
        return {
            "major_axis": None,
            "minor_axis": None,
            "axis_ratio": None,
            "eccentricity_ratio": None,
            "principal_angle_deg": None,
        }

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    cx = _safe_mean(xs)
    cy = _safe_mean(ys)
    if cx is None or cy is None:
        return {
            "major_axis": None,
            "minor_axis": None,
            "axis_ratio": None,
            "eccentricity_ratio": None,
            "principal_angle_deg": None,
        }

    dx = [x - cx for x in xs]
    dy = [y - cy for y in ys]
    sxx = sum(v * v for v in dx) / len(dx)
    syy = sum(v * v for v in dy) / len(dy)
    sxy = sum(a * b for a, b in zip(dx, dy)) / len(dx)

    angle_deg = math.degrees(0.5 * math.atan2(2 * sxy, sxx - syy))
    angle = math.radians(angle_deg)
    ux = math.cos(angle)
    uy = math.sin(angle)
    vx = -math.sin(angle)
    vy = math.cos(angle)

    projected_u = [ddx * ux + ddy * uy for ddx, ddy in zip(dx, dy)]
    projected_v = [ddx * vx + ddy * vy for ddx, ddy in zip(dx, dy)]
    major = max(projected_u) - min(projected_u)
    minor = max(projected_v) - min(projected_v)
    axis_ratio = (major / minor) if minor > 1e-12 else None
    eccentricity_ratio = (1 - (minor / major)) if major > 1e-12 else None

    return {
        "major_axis": major,
        "minor_axis": minor,
        "axis_ratio": axis_ratio,
        "eccentricity_ratio": eccentricity_ratio,
        "principal_angle_deg": angle_deg,
    }


def _polygon_area(points: list[tuple[float, float]]) -> float | None:
    if len(points) < 3:
        return None
    area = 0.0
    for i in range(len(points)):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % len(points)]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def _cross(o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _convex_hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    pts = sorted(set(points))
    if len(pts) <= 1:
        return pts

    lower: list[tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and _cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    upper: list[tuple[float, float]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and _cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    return lower[:-1] + upper[:-1]


def _envelope_area(points: list[tuple[float, float]]) -> float | None:
    if len(points) < 3:
        return None
    hull = _convex_hull(points)
    return _polygon_area(hull)


def _orientation(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> bool:
    return (
        min(a[0], c[0]) - 1e-12 <= b[0] <= max(a[0], c[0]) + 1e-12
        and min(a[1], c[1]) - 1e-12 <= b[1] <= max(a[1], c[1]) + 1e-12
    )


def _segments_intersect(
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    p4: tuple[float, float],
) -> bool:
    o1 = _orientation(p1, p2, p3)
    o2 = _orientation(p1, p2, p4)
    o3 = _orientation(p3, p4, p1)
    o4 = _orientation(p3, p4, p2)

    if (o1 > 0 > o2 or o1 < 0 < o2) and (o3 > 0 > o4 or o3 < 0 < o4):
        return True

    if abs(o1) <= 1e-12 and _on_segment(p1, p3, p2):
        return True
    if abs(o2) <= 1e-12 and _on_segment(p1, p4, p2):
        return True
    if abs(o3) <= 1e-12 and _on_segment(p3, p1, p4):
        return True
    if abs(o4) <= 1e-12 and _on_segment(p3, p2, p4):
        return True
    return False


def _self_intersection_count(points: list[tuple[float, float]]) -> int:
    if len(points) < 4:
        return 0

    count = 0
    segments = [(points[i], points[i + 1]) for i in range(len(points) - 1)]
    for i in range(len(segments)):
        for j in range(i + 1, len(segments)):
            if abs(i - j) <= 1:
                continue
            if i == 0 and j == len(segments) - 1:
                continue
            if _segments_intersect(segments[i][0], segments[i][1], segments[j][0], segments[j][1]):
                count += 1
    return count


def _normalize_cycle_count(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(value):
        iv = int(value)
        return iv if iv > 0 else None
    if isinstance(value, str):
        try:
            iv = int(float(value))
            return iv if iv > 0 else None
        except ValueError:
            return None
    return None


def _split_points_by_cycle_count(
    raw_points: list[tuple[float, float]],
    cycle_count: int | None,
    min_points_per_cycle: int = 4,
) -> list[list[tuple[float, float]]]:
    if not raw_points or cycle_count is None or cycle_count <= 0:
        return []

    total_points = len(raw_points)
    if total_points < cycle_count * min_points_per_cycle:
        return []

    base = total_points // cycle_count
    remainder = total_points % cycle_count
    if base < min_points_per_cycle:
        return []

    cycles: list[list[tuple[float, float]]] = []
    start = 0
    for i in range(cycle_count):
        extra = 1 if i < remainder else 0
        end = start + base + extra
        cycle_points = raw_points[start:end]
        if len(cycle_points) >= min_points_per_cycle:
            cycles.append(cycle_points)
        start = end
    return cycles


def _resample_cycle_by_angle(points: list[tuple[float, float]], sample_count: int = 64) -> list[float]:
    center = _center_metrics(points)
    cx = center["center_x"]
    cy = center["center_y"]
    if cx is None or cy is None:
        return []

    bucket_values: list[list[float]] = [[] for _ in range(sample_count)]
    for x, y in points:
        angle = math.atan2(y - cy, x - cx)
        if angle < 0:
            angle += 2 * math.pi
        idx = min(sample_count - 1, int(angle / (2 * math.pi) * sample_count))
        radius = math.sqrt((x - cx) ** 2 + (y - cy) ** 2)
        bucket_values[idx].append(radius)

    profile = [(_safe_mean(bucket) or 0.0) for bucket in bucket_values]
    mean_r = _safe_mean(profile)
    if mean_r in (None, 0.0):
        return profile
    return [v / mean_r for v in profile]


def _profile_similarity(a: list[float], b: list[float]) -> float | None:
    if not a or not b or len(a) != len(b):
        return None
    diff = _safe_mean([abs(x - y) for x, y in zip(a, b)])
    if diff is None:
        return None
    return _clamp(1.0 - diff)


def _cycle_size_descriptor(points: list[tuple[float, float]]) -> tuple[float | None, float | None, float | None]:
    area = _polygon_area(points)
    principal = _principal_axis_metrics(points)
    return area, principal["major_axis"], principal["minor_axis"]


def _relative_similarity(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    denom = max(abs(a), abs(b), 1e-12)
    return _clamp(1.0 - abs(a - b) / denom)


def _repetition_metrics(raw_points: list[tuple[float, float]], cycle_count: int | None) -> dict[str, Any]:
    cycles = _split_points_by_cycle_count(raw_points, cycle_count)
    if len(cycles) < 2:
        return {
            "repetition_score": None,
            "cycle_shape_similarity": None,
            "cycle_size_similarity": None,
            "cycles": cycles,
        }

    profiles = [_resample_cycle_by_angle(cycle, sample_count=64) for cycle in cycles]
    shape_similarities: list[float] = []
    size_similarities: list[float] = []

    descriptors = [_cycle_size_descriptor(cycle) for cycle in cycles]
    for i in range(len(cycles) - 1):
        shape_similarity = _profile_similarity(profiles[i], profiles[i + 1])
        if shape_similarity is not None:
            shape_similarities.append(shape_similarity)

        area_sim = _relative_similarity(descriptors[i][0], descriptors[i + 1][0])
        major_sim = _relative_similarity(descriptors[i][1], descriptors[i + 1][1])
        minor_sim = _relative_similarity(descriptors[i][2], descriptors[i + 1][2])
        size_parts = [v for v in [area_sim, major_sim, minor_sim] if v is not None]
        if size_parts:
            size_similarities.append(sum(size_parts) / len(size_parts))

    cycle_shape_similarity = _safe_mean(shape_similarities)
    cycle_size_similarity = _safe_mean(size_similarities)

    if cycle_shape_similarity is None and cycle_size_similarity is None:
        repetition_score = None
    elif cycle_shape_similarity is None:
        repetition_score = cycle_size_similarity
    elif cycle_size_similarity is None:
        repetition_score = cycle_shape_similarity
    else:
        repetition_score = _clamp(0.6 * cycle_shape_similarity + 0.4 * cycle_size_similarity)

    return {
        "repetition_score": repetition_score,
        "cycle_shape_similarity": cycle_shape_similarity,
        "cycle_size_similarity": cycle_size_similarity,
        "cycles": cycles,
    }


def _orbit_rotation_vote(points: list[tuple[float, float]]) -> int:
    if len(points) < 3:
        return 0

    vote = 0
    for i in range(len(points) - 2):
        ax, ay = points[i]
        bx, by = points[i + 1]
        cx, cy = points[i + 2]
        cross = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
        if cross > 0:
            vote += 1
        elif cross < 0:
            vote -= 1
    return vote


def _precession_direction(points_1x: list[tuple[float, float]]) -> str | None:
    vote = _orbit_rotation_vote(points_1x)
    if vote > 0:
        return "正进动"
    if vote < 0:
        return "反进动"
    return None


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    q = min(max(q, 0.0), 1.0)
    idx = q * (len(ordered) - 1)
    low = int(math.floor(idx))
    high = int(math.ceil(idx))
    if low == high:
        return ordered[low]
    frac = idx - low
    return ordered[low] * (1.0 - frac) + ordered[high] * frac


def _circular_smooth_points(points: list[tuple[float, float]], window_radius: int = 1) -> list[tuple[float, float]]:
    if len(points) < 3 or window_radius <= 0:
        return list(points)
    n = len(points)
    smoothed: list[tuple[float, float]] = []
    for i in range(n):
        xs: list[float] = []
        ys: list[float] = []
        for k in range(-window_radius, window_radius + 1):
            x, y = points[(i + k) % n]
            xs.append(x)
            ys.append(y)
        smoothed.append((sum(xs) / len(xs), sum(ys) / len(ys)))
    return smoothed


def _turn_angle_deg(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    v1x, v1y = a[0] - b[0], a[1] - b[1]
    v2x, v2y = c[0] - b[0], c[1] - b[1]
    n1 = math.hypot(v1x, v1y)
    n2 = math.hypot(v2x, v2y)
    if n1 <= 1e-12 or n2 <= 1e-12:
        return 180.0
    cos_theta = max(-1.0, min(1.0, (v1x * v2x + v1y * v2y) / (n1 * n2)))
    return math.degrees(math.acos(cos_theta))


def _polyline_collinearity(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
    ac_len = _distance(a, c)
    if ac_len <= 1e-12:
        return 0.0

    area2 = abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))
    point_line_distance = area2 / ac_len
    local_scale = max(_distance(a, b), _distance(b, c), ac_len, 1e-12)
    deviation_ratio = point_line_distance / local_scale

    angle_penalty = abs(180.0 - _turn_angle_deg(a, b, c))
    deviation_score = _clamp(1.0 - deviation_ratio / 0.18)
    angle_score = _clamp(1.0 - angle_penalty / 28.0)
    return _clamp(0.6 * deviation_score + 0.4 * angle_score)


def _straight_transition_score(points: list[tuple[float, float]]) -> float:
    if len(points) < 5:
        return 0.0

    smoothed = _circular_smooth_points(points, window_radius=1)
    local_scores: list[float] = []
    flags: list[bool] = []
    for i in range(1, len(smoothed) - 1):
        score = _polyline_collinearity(smoothed[i - 1], smoothed[i], smoothed[i + 1])
        local_scores.append(score)
        flags.append(score >= 0.74)

    if not local_scores:
        return 0.0

    best_run = 0
    current_run = 0
    for flag in flags:
        if flag:
            current_run += 1
            best_run = max(best_run, current_run)
        else:
            current_run = 0

    straight_ratio = sum(1 for flag in flags if flag) / len(flags)
    longest_ratio = best_run / max(len(flags) * 0.18, 1.0)
    mean_top = _safe_mean(sorted(local_scores, reverse=True)[: max(3, len(local_scores) // 5)]) or 0.0
    return _clamp(0.45 * straight_ratio + 0.35 * _clamp(longest_ratio) + 0.20 * mean_top)


def _project_to_axes(points: list[tuple[float, float]], angle_deg: float | None) -> list[tuple[float, float]]:
    if not points or angle_deg is None:
        return []

    center = _center_metrics(points)
    cx = center["center_x"]
    cy = center["center_y"]
    if cx is None or cy is None:
        return []

    angle = math.radians(angle_deg)
    ux = math.cos(angle)
    uy = math.sin(angle)
    vx = -math.sin(angle)
    vy = math.cos(angle)

    result: list[tuple[float, float]] = []
    for x, y in points:
        dx = x - cx
        dy = y - cy
        u = dx * ux + dy * uy
        v = dx * vx + dy * vy
        result.append((u, v))
    return result


def _shape_asymmetry(projected: list[tuple[float, float]]) -> float | None:
    if len(projected) < 4:
        return None

    pos = [abs(v) for u, v in projected if u >= 0]
    neg = [abs(v) for u, v in projected if u < 0]
    pos_size = max(pos, default=None)
    neg_size = max(neg, default=None)
    if pos_size in (None, 0.0) or neg_size is None:
        return None
    return abs(pos_size - neg_size) / max(pos_size, neg_size, 1e-12)


def _ellipse_fit_residual(points: list[tuple[float, float]], angle_deg: float | None, major_axis: float | None, minor_axis: float | None) -> float | None:
    if len(points) < 8 or angle_deg is None or major_axis in (None, 0.0) or minor_axis in (None, 0.0):
        return None
    projected = _project_to_axes(_circular_smooth_points(points, window_radius=1), angle_deg)
    if not projected:
        return None

    abs_us = [abs(u) for u, _ in projected]
    abs_vs = [abs(v) for _, v in projected]
    a = _percentile(abs_us, 0.95)
    b = _percentile(abs_vs, 0.95)
    if a in (None, 0.0) or b in (None, 0.0):
        return None

    residuals: list[float] = []
    for u, v in projected:
        theta = math.atan2(v, u)
        denom = math.sqrt((math.cos(theta) / max(a, 1e-12)) ** 2 + (math.sin(theta) / max(b, 1e-12)) ** 2)
        if denom <= 1e-12:
            continue
        expected_r = 1.0 / denom
        observed_r = math.hypot(u, v)
        residuals.append(abs(observed_r - expected_r) / max(expected_r, 1e-12))
    if not residuals:
        return None
    robust_mean = _safe_mean(sorted(residuals)[: max(5, int(len(residuals) * 0.9))])
    return None if robust_mean is None else float(robust_mean)



def _radius_cv(points: list[tuple[float, float]]) -> float | None:
    if len(points) < 4:
        return None
    center = _center_metrics(points)
    cx = center["center_x"]
    cy = center["center_y"]
    if cx is None or cy is None:
        return None

    radii = [math.hypot(x - cx, y - cy) for x, y in points]
    mean_r = _safe_mean(radii)
    if mean_r in (None, 0.0):
        return None
    return _safe_std(radii) / max(mean_r, 1e-12)


def _score_axis_near_one(axis_ratio: float | None) -> float | None:
    if axis_ratio is None:
        return None
    return _clamp(1.0 - abs(axis_ratio - 1.0) / 0.35)


def _score_axis_ellipse_range(axis_ratio: float | None) -> float | None:
    if axis_ratio is None or axis_ratio <= 1.0:
        return 0.0
    if axis_ratio < 1.15:
        return _clamp((axis_ratio - 1.0) / 0.15)
    if axis_ratio <= 4.0:
        return 1.0
    if axis_ratio < 6.0:
        return _clamp(1.0 - (axis_ratio - 4.0) / 2.0)
    return 0.0


def _weighted_mean(pairs: list[tuple[float | None, float]]) -> float | None:
    valid = [(v, w) for v, w in pairs if v is not None and w > 0]
    if not valid:
        return None
    total_w = sum(w for _, w in valid)
    if total_w <= 0:
        return None
    return sum(v * w for v, w in valid) / total_w


def _classify_circle_or_ellipse(
    concavity_score: float | None,
    figure_eight_score: float | None,
    crescent_score: float | None,
    self_intersection_count: int,
    radius_cv: float | None,
    axis_ratio: float | None,
    ellipse_fit_residual: float | None,
) -> dict[str, float | str | None]:
    negative_reasons: list[str] = []
    if self_intersection_count > 0:
        negative_reasons.append("存在自交")
    if concavity_score is not None and concavity_score >= 0.28:
        negative_reasons.append("凹陷特征明显")
    if figure_eight_score is not None and figure_eight_score >= 0.50:
        negative_reasons.append("8字形特征明显")
    if crescent_score is not None and crescent_score >= 0.45:
        negative_reasons.append("月牙形特征明显")

    penalty_score = _weighted_mean([
        (None if concavity_score is None else _clamp(1.0 - concavity_score / 0.25), 0.65),
        (1.0 if self_intersection_count == 0 else 0.0, 0.35),
    ])
    circle_score = _weighted_mean([
        (None if radius_cv is None else _clamp(1.0 - radius_cv / 0.24), 0.45),
        (_score_axis_near_one(axis_ratio), 0.30),
        (penalty_score, 0.25),
    ])
    ellipse_score = _weighted_mean([
        (None if ellipse_fit_residual is None else _clamp(1.0 - ellipse_fit_residual / 0.30), 0.40),
        (1.0 if self_intersection_count == 0 else 0.0, 0.20),
        (None if concavity_score is None else _clamp(1.0 - concavity_score / 0.25), 0.20),
        (_score_axis_ellipse_range(axis_ratio), 0.20),
    ])

    if negative_reasons:
        return {
            "circle_score": circle_score,
            "ellipse_score": ellipse_score,
            "shape_label": None,
            "negative_reason": "、".join(negative_reasons),
        }

    shape_label = None
    if circle_score is not None and ellipse_score is not None:
        if circle_score >= 0.62 and circle_score >= ellipse_score + 0.04:
            shape_label = "圆形"
        elif ellipse_score >= 0.62 and ellipse_score >= circle_score:
            shape_label = "椭圆形"
    elif circle_score is not None and circle_score >= 0.66:
        shape_label = "圆形"
    elif ellipse_score is not None and ellipse_score >= 0.66:
        shape_label = "椭圆形"

    return {
        "circle_score": circle_score,
        "ellipse_score": ellipse_score,
        "shape_label": shape_label,
        "negative_reason": None,
    }


def _first_cycle_shape_metrics(points: list[tuple[float, float]]) -> dict[str, float | int | None]:
    if len(points) < 4:
        return {
            "concavity_score": None,
            "straight_transition_score": None,
            "figure_eight_score": None,
            "crescent_score": None,
            "orbit_area": None,
            "major_axis_length": None,
            "minor_axis_length": None,
            "axis_ratio": None,
            "roundness_score": None,
            "ellipse_fit_residual": None,
            "self_intersection_count": 0,
            "radius_cv": None,
            "circle_likeness_score": None,
            "ellipse_likeness_score": None,
            "shape_label": None,
            "shape_negative_reason": None,
        }

    area = _polygon_area(points)
    hull_area = _envelope_area(points)
    fill_ratio = None if area is None or hull_area in (None, 0.0) else area / hull_area
    principal = _principal_axis_metrics(points)
    projected = _project_to_axes(points, principal["principal_angle_deg"])

    straight_transition_score = _straight_transition_score(points)
    self_intersections = _self_intersection_count(points)

    waist_ratio = None
    if projected:
        us = [u for u, _ in projected]
        u_abs_max = max((abs(u) for u in us), default=0.0)
        if u_abs_max > 1e-12:
            waist_band = max(u_abs_max * 0.15, 1e-12)
            lobe_band_low = u_abs_max * 0.45
            lobe_band_high = u_abs_max * 0.85

            waist_vs = [abs(v) for u, v in projected if abs(u) <= waist_band]
            lobe_vs = [abs(v) for u, v in projected if lobe_band_low <= abs(u) <= lobe_band_high]
            waist_width = (2 * max(waist_vs)) if waist_vs else None
            lobe_width = (2 * max(lobe_vs)) if lobe_vs else None
            if waist_width is not None and lobe_width not in (None, 0.0):
                waist_ratio = waist_width / lobe_width

    figure_eight_score = None
    if waist_ratio is not None:
        figure_eight_score = _clamp(1.0 - waist_ratio)
        if self_intersections > 0:
            figure_eight_score = _clamp(figure_eight_score + 0.35)
    elif self_intersections > 0:
        figure_eight_score = 0.6

    concavity_score = None if fill_ratio is None else _clamp(1.0 - fill_ratio)

    crescent_score = None
    asymmetry_score = _shape_asymmetry(projected)
    if concavity_score is not None:
        crescent_base = 0.7 * concavity_score + 0.3 * (asymmetry_score or 0.0)
        if figure_eight_score is not None:
            crescent_base *= (1.0 - min(figure_eight_score, 0.8) * 0.6)
        crescent_score = _clamp(crescent_base)

    axis_ratio = principal["axis_ratio"]
    roundness_score = None if axis_ratio is None or axis_ratio <= 0 else _clamp(1.0 / axis_ratio)
    ellipse_fit_residual = _ellipse_fit_residual(
        points,
        principal["principal_angle_deg"],
        principal["major_axis"],
        principal["minor_axis"],
    )
    radius_cv = _radius_cv(points)
    shape_classification = _classify_circle_or_ellipse(
        concavity_score=concavity_score,
        figure_eight_score=figure_eight_score,
        crescent_score=crescent_score,
        self_intersection_count=self_intersections,
        radius_cv=radius_cv,
        axis_ratio=axis_ratio,
        ellipse_fit_residual=ellipse_fit_residual,
    )

    return {
        "concavity_score": concavity_score,
        "straight_transition_score": straight_transition_score,
        "figure_eight_score": figure_eight_score,
        "crescent_score": crescent_score,
        "orbit_area": area,
        "major_axis_length": principal["major_axis"],
        "minor_axis_length": principal["minor_axis"],
        "axis_ratio": axis_ratio,
        "roundness_score": roundness_score,
        "ellipse_fit_residual": ellipse_fit_residual,
        "self_intersection_count": self_intersections,
        "radius_cv": radius_cv,
        "circle_likeness_score": shape_classification["circle_score"],
        "ellipse_likeness_score": shape_classification["ellipse_score"],
        "shape_label": shape_classification["shape_label"],
        "shape_negative_reason": shape_classification["negative_reason"],
    }


def _build_feature_detail(
    data: dict[str, Any],
    cycle_count: int | None = None,
) -> tuple[OrbitCenterlineFeatureDetail, list[list[tuple[float, float]]]]:
    raw_points = _extract_xy(data.get("points") or [])
    points_1x = _extract_xy(data.get("points_1x") or [])

    repetition = _repetition_metrics(raw_points, cycle_count=cycle_count)
    parsed_cycles = repetition["cycles"] if isinstance(repetition.get("cycles"), list) else []
    first_cycle_points = parsed_cycles[0] if parsed_cycles else []
    first_cycle_metrics = _first_cycle_shape_metrics(first_cycle_points)

    detail = OrbitCenterlineFeatureDetail(
        raw_envelope_area=_round_float(_envelope_area(raw_points), 6),
        raw_repetition_score=_round_float(repetition["repetition_score"], 6),
        raw_cycle_shape_similarity=_round_float(repetition["cycle_shape_similarity"], 6),
        raw_cycle_size_similarity=_round_float(repetition["cycle_size_similarity"], 6),
        one_x_precession_direction=_precession_direction(points_1x),
        first_cycle_concavity_score=_round_float(first_cycle_metrics["concavity_score"], 6),
        first_cycle_straight_transition_score=_round_float(first_cycle_metrics["straight_transition_score"], 6),
        first_cycle_figure_eight_score=_round_float(first_cycle_metrics["figure_eight_score"], 6),
        first_cycle_crescent_score=_round_float(first_cycle_metrics["crescent_score"], 6),
        first_cycle_orbit_area=_round_float(first_cycle_metrics["orbit_area"], 6),
        first_cycle_major_axis_length=_round_float(first_cycle_metrics["major_axis_length"], 6),
        first_cycle_minor_axis_length=_round_float(first_cycle_metrics["minor_axis_length"], 6),
        first_cycle_axis_ratio=_round_float(first_cycle_metrics["axis_ratio"], 6),
        first_cycle_roundness_score=_round_float(first_cycle_metrics["roundness_score"], 6),
        first_cycle_ellipse_fit_residual=_round_float(first_cycle_metrics["ellipse_fit_residual"], 6),
        first_cycle_self_intersection_count=int(first_cycle_metrics["self_intersection_count"] or 0),
        first_cycle_radius_cv=_round_float(first_cycle_metrics["radius_cv"], 6),
        first_cycle_circle_likeness_score=_round_float(first_cycle_metrics["circle_likeness_score"], 6),
        first_cycle_ellipse_likeness_score=_round_float(first_cycle_metrics["ellipse_likeness_score"], 6),
        first_cycle_shape_label=first_cycle_metrics["shape_label"],
    )
    return detail, parsed_cycles


def _build_text_features(detail: OrbitCenterlineFeatureDetail) -> list[str]:
    features: list[str] = []

    if detail.raw_envelope_area is not None:
        features.append(f"原始轨迹包络面积={detail.raw_envelope_area} μm²")
    if detail.raw_cycle_shape_similarity is not None:
        features.append(f"原始轨迹周期间形状相似性得分={detail.raw_cycle_shape_similarity}")
    if detail.raw_cycle_size_similarity is not None:
        features.append(f"原始轨迹周期间大小相似性得分={detail.raw_cycle_size_similarity}")
    if detail.raw_repetition_score is not None:
        features.append(f"原始轨迹重复性得分={detail.raw_repetition_score}")

    if detail.one_x_precession_direction is not None:
        features.append(f"1X进动方向={detail.one_x_precession_direction}")
    else:
        features.append("1X进动方向未能可靠判定")

    if detail.first_cycle_orbit_area is not None:
        features.append(f"第一周期轨迹面积={detail.first_cycle_orbit_area} μm²")
    if detail.first_cycle_concavity_score is not None:
        features.append(f"第一周期轨迹凸凹得分={detail.first_cycle_concavity_score}")
    if detail.first_cycle_straight_transition_score is not None:
        features.append(f"第一周期轨迹直线过渡得分={detail.first_cycle_straight_transition_score}")
    if detail.first_cycle_figure_eight_score is not None:
        features.append(f"第一周期轨迹8字形得分={detail.first_cycle_figure_eight_score}")
    if detail.first_cycle_crescent_score is not None:
        features.append(f"第一周期轨迹月牙形得分={detail.first_cycle_crescent_score}")
    if detail.first_cycle_major_axis_length is not None:
        features.append(f"第一周期轨迹长轴长度={detail.first_cycle_major_axis_length} μm")
    if detail.first_cycle_minor_axis_length is not None:
        features.append(f"第一周期轨迹短轴长度={detail.first_cycle_minor_axis_length} μm")
    if detail.first_cycle_axis_ratio is not None:
        features.append(f"第一周期轨迹长短轴比={detail.first_cycle_axis_ratio}")
    if detail.first_cycle_radius_cv is not None:
        features.append(f"第一周期轨迹半径变异系数={detail.first_cycle_radius_cv}")
    if detail.first_cycle_roundness_score is not None:
        features.append(f"第一周期轨迹近圆程度={detail.first_cycle_roundness_score}")
    if detail.first_cycle_ellipse_fit_residual is not None:
        features.append(f"第一周期轨迹椭圆拟合残差={detail.first_cycle_ellipse_fit_residual}")
    if detail.first_cycle_circle_likeness_score is not None:
        features.append(f"第一周期轨迹圆形相似度得分={detail.first_cycle_circle_likeness_score}")
    if detail.first_cycle_ellipse_likeness_score is not None:
        features.append(f"第一周期轨迹椭圆形相似度得分={detail.first_cycle_ellipse_likeness_score}")
    if detail.first_cycle_shape_label is not None:
        features.append(f"第一周期轨迹形状标签={detail.first_cycle_shape_label}")
    features.append(f"第一周期轨迹自交次数={detail.first_cycle_self_intersection_count}")

    return features[:20]


def _build_summary(detail: OrbitCenterlineFeatureDetail) -> list[str]:
    summary: list[str] = []

    if detail.raw_repetition_score is not None:
        if detail.raw_repetition_score >= 0.8:
            summary.append("原始轨迹多周期重复性较好")
        elif detail.raw_repetition_score <= 0.5:
            summary.append("原始轨迹多周期重复性较差")

    if detail.raw_cycle_shape_similarity is not None and detail.raw_cycle_size_similarity is not None:
        if detail.raw_cycle_shape_similarity >= 0.8 and detail.raw_cycle_size_similarity >= 0.8:
            summary.append("原始轨迹周期间形状和大小均较稳定")
        elif detail.raw_cycle_shape_similarity <= 0.5 or detail.raw_cycle_size_similarity <= 0.5:
            summary.append("原始轨迹周期间形状或大小变化较明显")

    if detail.one_x_precession_direction is not None:
        summary.append(f"1X轨迹表现为{detail.one_x_precession_direction}")

    negative_reasons: list[str] = []
    if detail.first_cycle_self_intersection_count > 0:
        negative_reasons.append("存在自交")
    if detail.first_cycle_concavity_score is not None and detail.first_cycle_concavity_score >= 0.28:
        negative_reasons.append("凹陷特征明显")
    if detail.first_cycle_figure_eight_score is not None and detail.first_cycle_figure_eight_score >= 0.50:
        negative_reasons.append("8字形特征明显")
    if detail.first_cycle_crescent_score is not None and detail.first_cycle_crescent_score >= 0.45:
        negative_reasons.append("月牙形特征明显")

    if negative_reasons:
        summary.append(f"第一周期轨迹先经过负面筛选，不赋予圆形/椭圆形标签（{'、'.join(negative_reasons)}）")
    else:
        if detail.first_cycle_shape_label == "圆形":
            summary.append("第一周期轨迹更接近圆形")
        elif detail.first_cycle_shape_label == "椭圆形":
            summary.append("第一周期轨迹更接近椭圆形")
        else:
            summary.append("第一周期轨迹未达到明确的圆形/椭圆形判定阈值")

    if detail.first_cycle_circle_likeness_score is not None and detail.first_cycle_ellipse_likeness_score is not None:
        if detail.first_cycle_circle_likeness_score >= detail.first_cycle_ellipse_likeness_score + 0.05:
            summary.append("正向判别中圆形相似度高于椭圆形相似度")
        elif detail.first_cycle_ellipse_likeness_score >= detail.first_cycle_circle_likeness_score:
            summary.append("正向判别中椭圆形相似度不低于圆形相似度")


    if detail.first_cycle_straight_transition_score is not None:
        if detail.first_cycle_straight_transition_score >= 0.7:
            summary.append("第一周期轨迹存在较明显直线过渡")
        elif detail.first_cycle_straight_transition_score <= 0.5:
            summary.append("第一周期轨迹直线过渡特征不明显")

    if detail.first_cycle_self_intersection_count > 0:
        summary.append("第一周期轨迹存在自交")

    return summary[:12]


async def _extract_orbit_centerline_features_impl(
    machine_id: str | None = None,
    bearing_id: str | None = None,
    time: str | None = None,
    time_ms: str | None = None,
    orbit_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    提取轴心轨迹与中心偏置特征。

    说明：输入点坐标会统一乘以 1000，缩放后按 μm 参与后续面积、长短轴等计算。

    输入格式一：直接传入原始轨迹数据
    {
      "machine_id": ".",
      "bearing_id": ".",
      "time_ms": ".",
      "probe_ids": [.],
      "cycles": 5,
      "data": {
        "points": [.],
        "points_1x": [.],
        "points_2x": [.],
        "purified_points": [.],
        "spectrum_components": [.],
        "speed": .,
        "probe_ids": [.],
        "cycles": 5
      }
    }

    输入格式二：只提供查询参数，工具内部按需调用 get_orbit_data_tool
    {
      "machine_id": ".",
      "bearing_id": "type_num/type_enum=70 的轴承 ID",
      "time": "趋势分析返回的异常毫秒时间戳，或可解析时间字符串",
      "time_ms": "趋势分析返回的异常毫秒时间戳，可选，优先于 time"
    }
    """
    if orbit_payload is None:
        orbit_payload = {}

    if "data" not in orbit_payload:
        payload_machine_id = str(machine_id or orbit_payload.get("machine_id") or "")
        payload_bearing_id = str(bearing_id or orbit_payload.get("bearing_id") or "")
        payload_time = str(time_ms or time or orbit_payload.get("time_ms") or orbit_payload.get("time") or "")
        if not payload_machine_id:
            raise ValueError("machine_id is required when orbit data is not provided")
        if not payload_bearing_id:
            raise ValueError("bearing_id is required when orbit data is not provided")
        if not payload_time:
            raise ValueError("time is required when orbit data is not provided")
        orbit_payload = await _get_orbit_data_impl(payload_machine_id, payload_bearing_id, payload_time)

    machine_id = str(orbit_payload.get("machine_id") or "")
    bearing_id = str(orbit_payload.get("bearing_id") or "")
    time_ms = str(orbit_payload.get("time_ms") or "")
    probe_ids = orbit_payload.get("probe_ids") or []

    data = orbit_payload.get("data") or {}
    if not isinstance(data, dict):
        data = {}

    raw_cycle_value = orbit_payload.get("cycles")
    if raw_cycle_value is None:
        raw_cycle_value = data.get("cycles")
    cycle_count = _normalize_cycle_count(raw_cycle_value)

    feature_details, parsed_cycles = _build_feature_detail(data, cycle_count=cycle_count)

    result = OrbitCenterlineAnalysisResult(
        machine_id=machine_id,
        bearing_id=bearing_id,
        time_ms=time_ms,
        summary=_build_summary(feature_details),
        text_features=_build_text_features(feature_details),
        feature_details=feature_details,
        probe_ids=probe_ids if isinstance(probe_ids, list) else [],
        cycle_count=cycle_count,
    )
    return result.model_dump()


@function_tool(strict_mode=False)
async def extract_orbit_centerline_features_tool(
    machine_id: str | None = None,
    bearing_id: str | None = None,
    time: str | None = None,
    time_ms: str | None = None,
    orbit_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return await _extract_orbit_centerline_features_impl(
        machine_id=machine_id,
        bearing_id=bearing_id,
        time=time,
        time_ms=time_ms,
        orbit_payload=orbit_payload,
    )


async def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("用法: python extract_orbit_centerline_features_tool.py '<orbit_payload_json>'")

    payload = json.loads(sys.argv[1])
    if not isinstance(payload, dict):
        raise SystemExit("orbit_payload_json 必须是 JSON 对象")
    result = await extract_orbit_centerline_features_tool(**payload)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
