#!/usr/bin/env python3
"""统一监测数据获取脚本 — monitoring-data Skill。

根据测点 positionType 自动路由到 2K/6K/7K/8K/9K 端点，内联 HTTP 调用 InS 平台，
获取趋势数据、波形数据和事件数据。

Usage:
    python fetch_monitoring_data.py \\
      --point-ids "id1,id2,id3" \\
      --point-metadata '{"id1": {"type": 83, "machineId": "12345", "name": "驱动端水平振动", "componentName": "前轴承"}}' \\
      --start "2026-05-01T00:00:00" \\
      --end "2026-06-01T00:00:00" \\
      --include-waveform true \\
      --output-dir /mnt/user-data/outputs/

Environment:
    INS_BASE_URL           — InS 平台地址 (default: http://182.92.187.198)
    INS_ACCESS_TOKEN       — Bearer token
    INS_REFRESH_TOKEN      — 刷新 token（401 时自动刷新）
    DEER_FLOW_GATEWAY_URL  — Gateway 地址 (default: http://localhost:8001)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone

# numpy 用于波形 IFFT 重建
try:
    import numpy as np
    _NUMPY_AVAILABLE = True
except ImportError:
    _NUMPY_AVAILABLE = False
    np = None

# ===== 同级模块 =====
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _series_router import (
    resolve_endpoint_series,
    resolve_category,
    supports_waveform,
    default_features,
    get_wave_types,
    trend_path,
    wave_path,
    trend_density,
    trend_include_filter,
)

# ===== InS 连接配置 =====
INS_BASE = os.environ.get("INS_BASE_URL", "http://182.92.187.198")
GATEWAY_URL = os.environ.get("DEER_FLOW_GATEWAY_URL", "http://localhost:8001")
REFRESH_TOKEN = os.environ.get("INS_REFRESH_TOKEN", "")
_token = os.environ.get("INS_ACCESS_TOKEN", "")


def _try_refresh_token() -> bool:
    """尝试通过 Gateway 刷新 access token。"""
    global _token
    if not REFRESH_TOKEN:
        return False
    try:
        body = json.dumps({"refresh_token": REFRESH_TOKEN}).encode("utf-8")
        req = urllib.request.Request(
            f"{GATEWAY_URL}/api/auth/ins-base/refresh",
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        new_token = data.get("token") or data.get("access_token")
        if new_token and isinstance(new_token, str):
            _token = new_token
            return True
    except Exception as e:
        print(f"[fetch] token refresh error: {e}", file=sys.stderr)
    return False


# 启动时主动获取 token：优先用环境变量，否则通过 refresh_token 获取
if not _token and REFRESH_TOKEN:
    if _try_refresh_token():
        print("[fetch] token 已通过 refresh_token 自动获取", file=sys.stderr)
    else:
        print("[fetch] ⚠ token 未设置且自动获取失败，API 请求将无认证", file=sys.stderr)


def _get(path: str, params: dict) -> dict:
    """HTTP GET 请求 InS 接口，支持 401 自动刷新重试。"""
    qs = "&".join(
        f"{k}={urllib.request.quote(str(v), safe=',')}"
        for k, v in params.items()
        if v is not None and v != ""
    )
    url = f"{INS_BASE}/{path.lstrip('/')}?{qs}"
    headers = {"Accept": "application/json"}
    if _token:
        headers["Authorization"] = f"Bearer {_token}"

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            pass
        print(f"[fetch] API 错误: HTTP {e.code} | {path} | {err_body}", file=sys.stderr)
        if e.code == 401 and _try_refresh_token():
            headers["Authorization"] = f"Bearer {_token}"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read())
        raise RuntimeError(f"InS API 返回 HTTP {e.code}: {path}") from e


def _date_to_ms(date_str: str) -> str:
    """将日期字符串转换为毫秒时间戳字符串。"""
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
            return str(int(dt.timestamp() * 1000))
        except ValueError:
            continue
    return date_str


# ===== 趋势数据获取与解析 =====

# 2K 中文名 → ASCII key 映射
_TWO_K_NAME_MAP = {
    "振动速度有效值": "v_rms", "加速度峰值": "a_peak", "加速度有效值": "a_rms",
    "位移峰峰值": "pp", "波形指数": "wave_index", "峰值指数": "peak_index",
    "脉冲指数": "pulse_index", "峭度指数": "kurtosis_index", "裕度指数": "margin_index",
    "歪度指数": "skewness_index", "转速": "speed", "过程量": "value",
}


def _extract_entry_values(entry: dict, features: list[str]) -> tuple[int | None, dict]:
    """从单条 dataArr 条目中提取时间戳和特征值。"""
    time_ms = entry.get("time") or entry.get("datatime")
    values = {}
    for f in features:
        v = entry.get(f)
        if isinstance(v, (int, float)) and v is not None:
            values[f] = float(v)
    return (int(time_ms) if time_ms else None, values)


def _parse_trend_8k_9k(body: dict, features: list[str]) -> list[dict]:
    """解析 8K/9K 趋势响应。

    8K/9K 响应 data 有两种格式：
    1) list：``[{gpid, dataArr: [{time, v_rms, ...}, ...]}, ...]``
       批量请求返回此格式，直接取 item["gpid"] 和 item["dataArr"]。
    2) dict：``{gpid: {trendData/dataArr: [{time, ...}, ...]}, ...}``
       单点请求可能返回此格式，按 gpid 遍历。
    """
    rows = []
    data = body.get("data", {})

    # ---- list 格式：批量响应 ----
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            # 8K 批量响应：item 直接包含 gpid + dataArr
            if "dataArr" in item and "gpid" in item:
                gpid = str(item["gpid"])
                for entry in item["dataArr"]:
                    if not isinstance(entry, dict):
                        continue
                    time_ms, values = _extract_entry_values(entry, features)
                    if time_ms is not None and values:
                        rows.append({"component_id": gpid, "time_ms": time_ms, "values": values})
                continue
            # 兼容旧格式：{gpid_value: {trendData: ...}}
            for gpid, gpid_data in item.items():
                if not isinstance(gpid_data, dict):
                    continue
                series_block = gpid_data.get("trendData") or gpid_data
                entries = series_block.get("dataArr") or series_block
                if isinstance(entries, list):
                    for entry in entries:
                        if not isinstance(entry, dict):
                            continue
                        time_ms, values = _extract_entry_values(entry, features)
                        if time_ms is not None and values:
                            rows.append({"component_id": gpid, "time_ms": time_ms, "values": values})
        return rows

    # ---- dict 格式：{gpid: {dataArr: ...}} ----
    if isinstance(data, dict):
        for gpid, gpid_data in data.items():
            if not isinstance(gpid_data, dict):
                continue
            series_block = gpid_data.get("trendData") or gpid_data
            entries = series_block.get("dataArr") or series_block
            if isinstance(entries, list):
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    time_ms, values = _extract_entry_values(entry, features)
                    if time_ms is not None and values:
                        rows.append({"component_id": gpid, "time_ms": time_ms, "values": values})

    return rows


def _parse_trend_2k_6k(body: dict, features: list[str]) -> list[dict]:
    """解析 2K/6K 趋势响应（单条格式）。"""
    rows = []
    data = body.get("data", {})
    if isinstance(data, list):
        items_list = data
    elif isinstance(data, dict):
        items_list = [{k: v} for k, v in data.items()]
    else:
        return rows

    for item in items_list:
        if not isinstance(item, dict):
            continue
        for gpid, gpid_data in item.items():
            if not isinstance(gpid_data, dict):
                continue
            values_block = gpid_data.get("values") or gpid_data.get("valueList") or gpid_data
            times_block = gpid_data.get("times") or gpid_data.get("timeList") or []
            if isinstance(values_block, dict):
                for key_cn, val_list in values_block.items():
                    key = _TWO_K_NAME_MAP.get(key_cn, key_cn)
                    if not isinstance(val_list, list):
                        continue
                    for i, v in enumerate(val_list):
                        if v is None or not isinstance(v, (int, float)):
                            continue
                        time_ms = times_block[i] if i < len(times_block) else None
                        if time_ms is None:
                            continue
                        rows.append({
                            "component_id": gpid,
                            "time_ms": int(time_ms),
                            "values": {key: float(v)},
                        })
    return rows


def _fetch_trend(
    pids: list[str],
    series: str,
    features: list[str],
    start_ms: str,
    end_ms: str,
) -> list[dict]:
    """获取趋势数据。"""
    path = trend_path(series)
    if not path:
        print(f"[fetch] series={series}: 无趋势端点，跳过", file=sys.stderr)
        return []
    params = {
        "gpids": ",".join(pids),
        "startTime": start_ms,
        "endTime": end_ms,
        "density": trend_density(series),
        "typeList": ",".join(features),
    }
    inc = trend_include_filter(series)
    if inc:
        params["includeFilter"] = inc

    print(f"[fetch] series={series}: 获取 {len(pids)} 个测点趋势 → {path}", file=sys.stderr)
    body = _get(path, params)
    if series in ("8k", "9k"):
        rows = _parse_trend_8k_9k(body, features)
    else:
        rows = _parse_trend_2k_6k(body, features)
    print(f"[fetch] series={series}: 解析得到 {len(rows)} 行", file=sys.stderr)
    return rows


# ===== 波形数据获取 =====

# Protobuf 解码依赖
try:
    import base64
    from google.protobuf.json_format import MessageToDict
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "features-tool"))
    from proto import wave_pb2
    _PROTO_AVAILABLE = True
except ImportError:
    _PROTO_AVAILABLE = False
    wave_pb2 = None
    MessageToDict = None


def _parse_wave_str(wave_str: str) -> dict:
    """base64 + protobuf 解码 waveStr。"""
    if not _PROTO_AVAILABLE:
        raise RuntimeError("protobuf 不可用，波形解码需要 docker sandbox 环境")
    wave = wave_pb2.WaveStream()
    wave.ParseFromString(base64.b64decode(wave_str))
    return MessageToDict(wave, preserving_proto_field_name=False)


def _ifft_to_wave(fft_amplitude: list, fft_phase: list) -> list:
    """
    通过IFFT从频谱幅值/相位重建时域波形

    这是 orbit-algo.js 中 initWaveByFFT 函数的 Python 实现。
    """
    if not _NUMPY_AVAILABLE:
        return []

    fft_amp = np.array(fft_amplitude)
    fft_ph = np.array(fft_phase)

    # 计算长度（2的幂次）
    mi = np.log2(len(fft_amp) * 2)
    length = int(2 ** mi)
    half = length // 2

    # 初始化复数数组
    complex_spectrum = np.zeros(length, dtype=complex)

    # 填充频谱数据（幅值/相位 → 复数）
    for i in range(len(fft_amp)):
        pp = fft_amp[i] / 4.0
        phase = fft_ph[i]
        real = pp * np.sin(phase)
        imag = -pp * np.cos(phase)
        complex_spectrum[i] = complex(real, imag)

    # 镜像对称填充（满足IFFT要求）
    for i in range(1, half):
        complex_spectrum[length - i] = np.conj(complex_spectrum[i])

    # IFFT反变换
    wave = np.fft.ifft(complex_spectrum).real

    return wave.tolist()


def _spectrum_to_wave(wave_data: dict) -> list | None:
    """
    从频谱数据重建时域波形（IFFT反变换）

    这是 orbit-algo.js 中 spectrum2Wave 函数的 Python 实现。
    """
    if not _NUMPY_AVAILABLE:
        return None

    spectrum = wave_data.get("spectrum")
    if not spectrum or not isinstance(spectrum, dict):
        return None

    freq = wave_data.get("freq")
    samples = wave_data.get("samples")

    if not freq or not samples:
        return None

    index = spectrum.get("index", [])
    amp = spectrum.get("amp", [])
    ph = spectrum.get("ph", [])

    if not index or not amp or not ph:
        return None

    # 步骤1: 将稀疏频谱转换为完整FFT数组
    line_count = samples // 2
    FFT_Amplitude = [0.0] * line_count
    FFT_Phase = [0.0] * line_count

    interval = freq / samples

    for i in range(len(index)):
        f = index[i] * freq / samples
        line = int(f / interval + interval * 0.01)

        if line < line_count:
            FFT_Amplitude[line] = amp[i]
            FFT_Phase[line] = 3.141592653589793 * (ph[i] / 180.0)  # 度转弧度

    # 步骤2: IFFT反变换重建波形
    return _ifft_to_wave(FFT_Amplitude, FFT_Phase)


def _extract_wave_y(wave_data: dict) -> list:
    """从解码后的波形数据提取时域波形。"""
    wave_type = wave_data.get("waveType", "UNKNOWN")

    # SHIFT 类型有原始时域数据
    if wave_type == "SHIFT" and "waveDataShift" in wave_data:
        shift = wave_data["waveDataShift"]
        if isinstance(shift, dict) and "wave" in shift:
            wave = shift["wave"]
            if isinstance(wave, list) and wave:
                return [float(v) for v in wave]

    # SPECTRUM 类型通过 IFFT 重建
    if wave_type == "SPECTRUM" or "spectrum" in wave_data:
        result = _spectrum_to_wave(wave_data)
        if result:
            return result

    # COMPLEX 类型
    if "complex" in wave_data:
        complex_data = wave_data["complex"]

        # 优先尝试 SHIFT
        if isinstance(complex_data, dict) and "waveDataShift" in complex_data:
            shift = complex_data["waveDataShift"]
            if isinstance(shift, dict) and "wave" in shift:
                wave = shift["wave"]
                if isinstance(wave, list) and wave:
                    return [float(v) for v in wave]

        # 尝试从频谱重建
        if isinstance(complex_data, dict) and "spectrum" in complex_data:
            temp_data = {
                "spectrum": complex_data["spectrum"],
                "freq": wave_data.get("freq"),
                "samples": wave_data.get("samples"),
            }
            result = _spectrum_to_wave(temp_data)
            if result:
                return result

    return []


def _extract_spectrum(wave_data: dict) -> dict:
    """提取频谱数据。"""
    spectrum = wave_data.get("spectrum")
    if isinstance(spectrum, dict) and spectrum.get("index"):
        return {
            "spec_x": [float(v) for v in spectrum.get("index", [])],
            "spec_y": [float(v) for v in spectrum.get("amp", [])],
        }
    complex_data = wave_data.get("complex")
    if isinstance(complex_data, dict):
        spectrum = complex_data.get("spectrum")
        if isinstance(spectrum, dict):
            return {
                "spec_x": [float(v) for v in spectrum.get("index", [])],
                "spec_y": [float(v) for v in spectrum.get("amp", [])],
            }
    return {"spec_x": [], "spec_y": []}


def _fetch_waveform(pid: str, series: str, time_ms: str) -> dict | None:
    """获取单个测点的波形数据。"""
    path = wave_path(series)
    if not path:
        print(f"[fetch] waveform: {pid} (series={series}) 无波形端点路径", file=sys.stderr)
        return None
    if series == "2k":
        params = {"gpid": pid, "time": time_ms}
    else:
        params = {"gpids": pid, "timepoint": time_ms}

    try:
        body = _get(path, params)
    except Exception as e:
        print(f"[fetch] waveform error for {pid}: {e}", file=sys.stderr)
        return None

    data = body.get("data", [])
    if not data or not isinstance(data, list):
        print(f"[fetch] waveform: {pid} API 返回 data 为空或非 list: {type(data).__name__}", file=sys.stderr)
        return None

    item = data[0] if data else {}
    wave_str = item.get("waveStr") or item.get("wave_str") or ""
    if not wave_str:
        print(f"[fetch] waveform: {pid} data[0] 中无 waveStr，item keys: {list(item.keys())[:10]}", file=sys.stderr)
        return None

    # base64 + protobuf 解码
    if not _PROTO_AVAILABLE:
        print(f"[fetch] waveform: {pid} protobuf 不可用，跳过波形获取", file=sys.stderr)
        return None

    try:
        # 去除空白字符
        clean = "".join(ch for ch in wave_str if not ch.isspace())
        wave_data = _parse_wave_str(clean)
    except Exception as e:
        print(f"[fetch] waveform: {pid} protobuf 解码失败: {e}", file=sys.stderr)
        return None

    # 提取波形和频谱
    wave_y = _extract_wave_y(wave_data)
    spectrum = _extract_spectrum(wave_data)
    sample_rate = float(wave_data.get("freq") or 0.0)
    samples = int(wave_data.get("samples") or len(wave_y) or 0)

    # 计算时域 x 轴（毫秒）
    wave_x = [(i / sample_rate * 1000.0) if sample_rate > 0 else float(i) for i in range(len(wave_y))]

    # 计算频谱频率轴
    spec_x = spectrum["spec_x"]
    spec_y = spectrum["spec_y"]
    if spec_x and sample_rate > 0 and samples > 0:
        spec_freq = [idx * sample_rate / samples for idx in spec_x]
    else:
        spec_freq = spec_x

    print(f"[fetch] waveform: {pid} 成功获取波形 (samples={len(wave_y)}, spectrum={len(spec_y)})", file=sys.stderr)
    return {
        "time_ms": int(time_ms),
        "wave_x": wave_x,
        "wave_y": wave_y,
        "spec_x": spec_freq,
        "spec_y": spec_y,
        "sample_rate": sample_rate,
        "speed": float(wave_data.get("speed") or 0.0),
    }


# ===== 主逻辑 =====

def _merge_values(rows: list[dict]) -> list[dict]:
    """合并同一 (component_id, time_ms) 的多行 values。"""
    merged: dict[tuple[str, int], dict] = {}
    for row in rows:
        key = (row["component_id"], row["time_ms"])
        if key not in merged:
            merged[key] = {**row, "values": {}}
        merged[key]["values"].update(row.get("values", {}))
    return list(merged.values())


def _extract_last_valid_time(
    all_trend: dict[str, list[dict]],
    point_ids: list[str],
) -> str | None:
    """从趋势数据中提取最后一个有效时间点。"""
    latest = 0
    for pid in point_ids:
        rows = all_trend.get(pid, [])
        for row in rows:
            t = row.get("time_ms", 0)
            if t > latest:
                latest = t
    return str(latest) if latest > 0 else None


def fetch_monitoring_data(
    point_ids: list[str],
    point_metadata: dict[str, dict],
    start_ms: str,
    end_ms: str,
    include_waveform: bool = False,
    output_dir: str = "/mnt/user-data/outputs",
) -> dict:
    """主入口：获取所有测点的监测数据。"""
    output_notes: list[str] = []

    # 1. 按 series 分组
    series_groups: dict[str, list[str]] = defaultdict(list)
    for pid in point_ids:
        meta = point_metadata.get(pid, {})
        ptype = meta.get("type", 0)
        series = resolve_endpoint_series(ptype)
        series_groups[series].append(pid)

    # 2. 按 series 分批获取趋势数据
    all_trend: dict[str, list[dict]] = {}
    for series, pids in series_groups.items():
        # 合并这批测点的所有特征
        features_set: set[str] = set()
        for pid in pids:
            ptype = point_metadata.get(pid, {}).get("type", 0)
            features_set.update(default_features(ptype))
        features = sorted(features_set)

        try:
            rows = _fetch_trend(pids, series, features, start_ms, end_ms)
        except Exception as e:
            output_notes.append(f"[{series}] 趋势获取失败: {e}")
            continue

        # 合并同一 (component_id, time_ms) 的 values
        merged = _merge_values(rows)
        for row in merged:
            pid = row["component_id"]
            all_trend.setdefault(pid, []).append(row)

    # 3. 波形数据 — 仅对有波形支持的测点类别
    all_waveform: dict[str, dict] = {}
    if include_waveform:
        wave_time = _extract_last_valid_time(all_trend, point_ids)
        if wave_time:
            for pid in point_ids:
                meta = point_metadata.get(pid, {})
                ptype = meta.get("type", 0)
                if not supports_waveform(ptype):
                    continue
                series = resolve_endpoint_series(ptype)
                wave_data = _fetch_waveform(pid, series, wave_time)
                if wave_data:
                    all_waveform[pid] = wave_data
                else:
                    output_notes.append(f"测点 {pid} (type={ptype}) 波形获取失败")

    # 4. 组装输出
    output = {
        "schema_version": "2.0",
        "points": [
            {
                "point_id": pid,
                "name": point_metadata.get(pid, {}).get("name", ""),
                "point_type": point_metadata.get(pid, {}).get("type", 0),
                "endpoint_series": resolve_endpoint_series(
                    point_metadata.get(pid, {}).get("type", 0)
                ),
                "category": resolve_category(
                    point_metadata.get(pid, {}).get("type", 0)
                ),
                "machine_id": point_metadata.get(pid, {}).get("machineId", ""),
                "component_name": point_metadata.get(pid, {}).get("componentName", ""),
                "supports_waveform": supports_waveform(
                    point_metadata.get(pid, {}).get("type", 0)
                ),
            }
            for pid in point_ids
        ],
        "time_range": {"start_ms": int(start_ms), "end_ms": int(end_ms)},
        "trend": all_trend,
        "waveform": all_waveform,
        "data_source": "ins",
        "data_notes": output_notes,
    }

    # 5. 写入文件
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "monitoring_data.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)

    print(f"[fetch] 数据获取完成: {output_path}", file=sys.stderr)
    print(f"[fetch] 测点数: {len(point_ids)}, 趋势点: {sum(len(v) for v in all_trend.values())}, "
          f"波形: {len(all_waveform)}",
          file=sys.stderr)

    return output


def main():
    parser = argparse.ArgumentParser(description="统一监测数据获取")
    parser.add_argument("--point-ids", required=True, help="测点 ID，逗号分隔")
    parser.add_argument("--point-metadata", required=True, help="测点元数据 JSON")
    parser.add_argument("--start", required=True, help="开始时间 (ISO 格式)")
    parser.add_argument("--end", required=True, help="结束时间 (ISO 格式)")
    parser.add_argument("--include-waveform", default="false", help="是否获取波形数据")
    parser.add_argument("--output-dir", default="/mnt/user-data/outputs", help="输出目录")
    args = parser.parse_args()

    point_ids = [p.strip() for p in args.point_ids.split(",") if p.strip()]
    point_metadata = json.loads(args.point_metadata)
    start_ms = _date_to_ms(args.start)
    end_ms = _date_to_ms(args.end)
    include_waveform = args.include_waveform.lower() in ("true", "1", "yes")

    # 诊断输出 — Agent 通过 stderr 定位问题，不需要绕过脚本
    print(f"[fetch] 配置: INS_BASE_URL={INS_BASE}, token={'已设置' if _token else '未设置'}", file=sys.stderr)
    print(f"[fetch] 测点: {point_ids}", file=sys.stderr)
    print(f"[fetch] 时间: {args.start} → {start_ms}ms ~ {args.end} → {end_ms}ms", file=sys.stderr)
    print(f"[fetch] 波形: {include_waveform}", file=sys.stderr)

    result = fetch_monitoring_data(
        point_ids=point_ids,
        point_metadata=point_metadata,
        start_ms=start_ms,
        end_ms=end_ms,
        include_waveform=include_waveform,
        output_dir=args.output_dir,
    )

    # 结果摘要 — 让 Agent 快速判断数据是否完整
    trend_total = sum(len(v) for v in result.get("trend", {}).values())
    trend_empty = [pid for pid, rows in result.get("trend", {}).items() if not rows]
    wave_count = len(result.get("waveform", {}))
    print(f"[fetch] 结果: 趋势 {trend_total} 行, 波形 {wave_count} 个测点", file=sys.stderr)
    if trend_empty:
        print(f"[fetch] ⚠ 以下测点无趋势数据: {trend_empty}", file=sys.stderr)
    if result.get("data_notes"):
        for note in result["data_notes"]:
            print(f"[fetch] 备注: {note}", file=sys.stderr)


if __name__ == "__main__":
    main()
