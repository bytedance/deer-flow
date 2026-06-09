---
name: abnormal-judgment-rotating
description: >
  旋转机组异常研判专属 Skill。提供异常事件拉取、监测数据获取、研判报告渲染和导出能力。
  配合 monitoring-data Skill（公共数据获取）使用，由异常研判 Agent 编排调用。
metadata:
  emoji: "🔍"
---

# Abnormal Judgment — Rotating

旋转机组异常研判专属 Skill。

## When to Use This Skill

当异常研判 Agent 需要：
- 拉取 SMS 异常事件详情
- 获取监测趋势/波形数据（通过 monitoring-data Skill）
- 生成研判报告可视化（趋势图、频谱图、明细表）
- 导出 Markdown 研判报告
- 构建 Handoff payload 转交故障诊断 Agent

## Preconditions

- 环境变量 `INS_ACCESS_TOKEN` 已注入（Deer Flow 运行时自动注入）
- 环境变量 `INS_REFRESH_TOKEN` 可用（用于 401 自动刷新）
- `monitoring-data` Skill 可用（数据获取依赖）

## Scripts

### query_abnormal_detail.py — 异常事件详情拉取

```bash
python /mnt/skills/custom/abnormal-judgment-rotating/scripts/query_abnormal_detail.py \
  --abnormal-id {abnormal_id} \
  --mac-id {mac_id} \
  --component-id {component_id} \
  --output /mnt/user-data/outputs/abnormal_detail.json
```

**参数**：
| 参数 | 必填 | 说明 |
|------|:----:|------|
| `--abnormal-id` | ✅ | 异常事件 ID |
| `--mac-id` | — | 设备 ID（合并到输出） |
| `--component-id` | — | 子设备 ID（合并到输出） |
| `--output` | — | 输出文件路径 |

**输出**：`abnormal_detail.json`，包含 `events[]` 数组，每个事件含 `type`, `eventLevel`, `jumpParams` 等。

---

### fetch_abnormal_monitoring.py — 监测数据获取（适配层）

```bash
python /mnt/skills/custom/abnormal-judgment-rotating/scripts/fetch_abnormal_monitoring.py \
  --input /mnt/user-data/outputs/abnormal_detail.json \
  --include-waveform auto \
  --output-dir /mnt/user-data/outputs/
```

**参数**：
| 参数 | 必填 | 说明 |
|------|:----:|------|
| `--input` | ✅ | `abnormal_detail.json` 路径 |
| `--include-waveform` | — | `auto`（默认，仅 type=t/w 且 eventLevel≥21）/ `true` / `false` |
| `--output-dir` | — | 输出目录，默认 `/mnt/user-data/outputs/` |

**内部调用**：`monitoring-data/fetch_monitoring_data.py`（公共 Skill）

**输出**：`abnormal_monitoring.json`，格式与 `monitoring_data.json` 一致：

```json
{
  "schema_version": "2.0",
  "points": [{"point_id": "...", "name": "...", "point_type": 83, "category": "vib"}],
  "time_range": {"start_ms": 0, "end_ms": 0},
  "trend": {"<point_id>": [{"time_ms": 0, "values": {"pp_value": 0.0, "rms": 0.0}}]},
  "waveform": {"<point_id>": {"time_ms": 0, "wave_x": [], "spec_x": []}},
  "events_source": "abnormal_detail.json"
}
```

---

### generate_abnormal_charts.py — 研判报告图表生成

```bash
python /mnt/skills/custom/abnormal-judgment-rotating/scripts/generate_abnormal_charts.py \
  --detail /mnt/user-data/outputs/abnormal_detail.json \
  --monitoring /mnt/user-data/outputs/abnormal_monitoring.json \
  --verdict /mnt/user-data/outputs/judgment_result.json \
  --mac-name "{mac_name}" \
  --component-name "{component_name}" \
  --mac-path "{mac_path}" \
  --output-dir /mnt/user-data/outputs/
```

**参数**：
| 参数 | 必填 | 说明 |
|------|:----:|------|
| `--detail` | ✅ | `abnormal_detail.json` 路径 |
| `--monitoring` | ✅ | `abnormal_monitoring.json` 路径 |
| `--verdict` | ✅ | `judgment_result.json` 路径（LLM 研判结论） |
| `--mac-name` | — | 设备名称（用于卡片标题） |
| `--component-name` | — | 子设备名称 |
| `--mac-path` | — | 设备路径 |
| `--output-dir` | — | 输出目录 |

**输出**：`charts.json`，包含：

| sequence | 组件 | 内容 |
|:--------:|------|------|
| 1 | `card` | 设备名 + 健康值 + 研判结论颜色 |
| 2 | `table` | 异常事件研判明细表 |
| 3-N | `echart` | 每个异常测点的趋势折线图（含异常时段标注） |
| N+1-M | `echart` | 有波形的测点的频谱图（含 1X/2X 标注线） |
| M+1 | `markdown` | 综合结论 + 证据链 + 处置建议 |

**渲染方式**：使用 `render_charts_file` 工具批量渲染，一次调用完成。

---

### export_abnormal_report.py — 研判报告导出

```bash
python /mnt/skills/custom/abnormal-judgment-rotating/scripts/export_abnormal_report.py \
  --detail /mnt/user-data/outputs/abnormal_detail.json \
  --monitoring /mnt/user-data/outputs/abnormal_monitoring.json \
  --verdict /mnt/user-data/outputs/judgment_result.json \
  --mac-name "{mac_name}" \
  --component-name "{component_name}" \
  --output-dir /mnt/user-data/outputs/
```

**参数**：
| 参数 | 必填 | 说明 |
|------|:----:|------|
| `--detail` | ✅ | `abnormal_detail.json` 路径 |
| `--monitoring` | ✅ | `abnormal_monitoring.json` 路径 |
| `--verdict` | ✅ | `judgment_result.json` 路径 |
| `--mac-name` | — | 设备名称 |
| `--component-name` | — | 子设备名称 |
| `--output-dir` | — | 输出目录 |

**输出**：`judgment_report.md`

**报告内容**：
- 设备信息 + 研判时间
- 异常事件明细表
- 证据链（趋势/频谱/波形）
- 综合结论 + 置信度
- 处置建议

---

### build_handoff.py — 构建 Handoff Payload

```bash
python /mnt/skills/custom/abnormal-judgment-rotating/scripts/build_handoff.py \
  --detail /mnt/user-data/outputs/abnormal_detail.json \
  --mac-id {mac_id} \
  --component-id {component_id} \
  --mac-name "{mac_name}" \
  --component-name "{component_name}" \
  --mac-path "{mac_path}" \
  --verdict real_fault \
  --confidence 0.85 \
  --fault-type unbalance_1x \
  --severity medium \
  --health 84.0 \
  --run-status normal \
  --evidence "证据1" --evidence "证据2" \
  --output /mnt/user-data/outputs/handoff_payload.json
```

**参数**：
| 参数 | 必填 | 说明 |
|------|:----:|------|
| `--detail` | ✅ | `abnormal_detail.json` 路径 |
| `--mac-id` | ✅ | 设备 ID |
| `--component-id` | ✅ | 子设备 ID |
| `--mac-name` | ✅ | 设备名称 |
| `--component-name` | ✅ | 子设备名称 |
| `--mac-path` | ✅ | 设备路径 |
| `--verdict` | ✅ | `real_fault` / `suspected` / `false_alarm` |
| `--confidence` | ✅ | 置信度（0-1） |
| `--fault-type` | — | 疑似故障码（如 `unbalance_1x`） |
| `--severity` | — | `critical` / `high` / `medium` / `low` |
| `--health` | — | 健康值 |
| `--run-status` | — | 运行状态 |
| `--evidence` | — | 证据字符串（可重复） |
| `--output` | ✅ | 输出文件路径 |

**输出**：`handoff_payload.json`，用于 `render_ui(agent_handoff)` 的 `handoff_data`。

---

## References

- `references/fault_codes.md` — 12 个故障码 + 快速特征映射表（供 LLM 研判时参考）

## Dependencies

- **monitoring-data Skill** — 提供 `fetch_monitoring_data.py` 数据获取能力
- **不依赖 features-tool** — HTTP 调用和 token 管理由 monitoring-data 处理

## Output Convention

- 所有脚本输出 JSON 文件到 `--output-dir` 指定目录
- 错误信息输出到 stderr，不阻塞 Agent 主流程
- 认证通过环境变量（`INS_ACCESS_TOKEN`），不硬编码
