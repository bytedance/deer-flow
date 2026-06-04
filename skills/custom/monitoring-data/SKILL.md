---
name: monitoring-data
description: >
  公共监测数据获取 Skill。根据测点 positionType 自动路由到 2K/6K/7K/8K/9K 端点，
  内联 HTTP 调用 InS 平台，获取趋势数据、波形数据和事件数据。
  任何需要监测数据的 Agent 均可调用，不依赖 features-tool。
metadata:
  emoji: "📡"
---

# monitoring-data — 监测数据获取

## When to Use This Skill

当需要从 InS 平台获取设备监测原始数据时调用本 Skill：
- 获取测点趋势数据（支持 29 种 positionType，5 个 series 端点）
- 获取波形/频谱数据（仅 vib/vibc/thickness 类别测点）
- 获取事件数据（仅 8K/9K 设备）

## Preconditions

- 环境变量 `INS_ACCESS_TOKEN` 已注入（Deer Flow 运行时自动注入）
- 环境变量 `INS_REFRESH_TOKEN` 可用（用于 401 自动刷新）

## Scripts

### fetch_monitoring_data.py

统一数据获取入口。根据测点 positionType 自动路由到对应 series 端点。

```bash
python /mnt/skills/custom/monitoring-data/scripts/fetch_monitoring_data.py \
  --point-ids "id1,id2,id3" \
  --point-metadata '{"id1": {"type": 83, "machineId": "12345", "name": "驱动端水平振动", "componentName": "前轴承"}}' \
  --start "2026-05-01T00:00:00" \
  --end "2026-06-01T00:00:00" \
  --include-waveform true \
  --output-dir /mnt/user-data/outputs/
```

**参数说明**：
| 参数 | 必填 | 说明 |
|------|------|------|
| `--point-ids` | ✅ | 测点 ID，逗号分隔 |
| `--point-metadata` | ✅ | 测点元数据 JSON，key 为 point_id，value 含 `type`(positionType)、`machineId`、`name`、`componentName` |
| `--start` | ✅ | 开始时间，ISO 格式 |
| `--end` | ✅ | 结束时间，ISO 格式 |
| `--include-waveform` | — | 是否获取波形数据，默认 false。仅对 vib/vibc/thickness 类别生效 |
| `--output-dir` | — | 输出目录，默认 `/mnt/user-data/outputs/` |

**输出**：`monitoring_data.json`

```json
{
  "schema_version": "2.0",
  "points": [{"point_id", "name", "point_type", "endpoint_series", "category", "machine_id", "component_name", "supports_waveform"}],
  "time_range": {"start_ms": 0, "end_ms": 0},
  "trend": {"point_id": [{"time_ms": 0, "values": {"feature": 0.0}}]},
  "waveform": {"point_id": {"time_ms": 0, "wave_x": [], "wave_y": [], "spec_x": [], "spec_y": [], "sample_rate": 0, "speed": 0}},
  "events": {"machine_id": [{"type": 0, "time_ms": 0}]},
  "data_source": "ins",
  "data_notes": []
}
```

### _series_router.py（内部模块）

positionType → (series, category, waveform) 三级路由。被 `fetch_monitoring_data.py` 导入使用。

**29 种 positionType** 覆盖：
- **vib** (23, 24, 26, 27, 83)：振动测点，有波形
- **vibc** (91-96, 99)：机组振动测点，有波形 (SHIFT/SPECTRUM/RUNOUT)
- **key** (81, 97)：键相/转速，无波形
- **speed** (29)：转速，无波形
- **process** (22, 25, 28, 82, 84, 98, 163)：过程量，无波形
- **process_6k** (61)：6K 过程量（含腐蚀参数），无波形
- **thickness** (62, 64)：测厚，有 UT 波形
- **probe** (63)：腐蚀探针，无波形
- **leak** (161, 162)：泄漏，无波形
- **flux** (30)：磁通量，无波形

## Dependencies

- **不依赖 features-tool** — HTTP 调用内联实现（urllib）
- 被 monitoring-analysis Agent 和 monitoring-analysis Skill 调用

## Output Convention

- 趋势数据统一格式：`{component_id, time_ms, values: {feature: float}}`
- 2K 中文名自动映射为 ASCII key（如 "振动速度有效值" → "v_rms"）
- 波形数据仅对有波形支持的测点类别（vib/vibc/thickness）

## Notes

- 7K 端点路径 `/ins-os-view/sg7kData/getTrendDataHis` 待验证
- 波形获取失败不阻塞整体流程，记录到 `data_notes`
- token 401 自动通过 Gateway 刷新
