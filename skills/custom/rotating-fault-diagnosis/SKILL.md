---
name: rotating-fault-diagnosis
description: Use this skill when the user wants the rotating machinery diagnosis entry scripts. This skill wraps the rotating diagnosis CLI entry points.
metadata:
  emoji: "⚙️"
---

# Rotating Fault Diagnosis

Use this skill to invoke the rotating diagnosis entry scripts under its own skill boundary.

## When to Use This Skill

Use this skill when the user:

- Needs the rotating machinery diagnosis pipeline entry scripts
- Needs a stable wrapper for the real rule runtime, payload mapping, or report export

## Preconditions

- The runtime can execute `python3`
- The current user token is available as `INS_ACCESS_TOKEN` or `--access-token`
- `INS_BASE_URL` may be provided via `config.yaml` or left at the tool default

## Execution Rules

- Prefer the wrapper scripts in this skill directory
- Prefer `run_rotating_rule_diagnosis.py` → `build_rotating_report_payload.py` → `export_report.py`
- Return the underlying script output directly unless the user asks for summarization

## Scripts

### 诊断流水线
- `scripts/run_rotating_rule_diagnosis.py` — 受管规则运行时入口
- `scripts/build_rotating_report_payload.py` — 构建报告 payload
- `scripts/export_report.py` — 报告导出（md/pdf）
- `scripts/export_diagnosis_report.py` — 诊断报告 Markdown 渲染
- `scripts/query_diagnosis.py` — 诊断数据查询（Stage 1）
- `scripts/diagnosis_features.py` — 诊断特征提取（Stage 2）
- `scripts/build_device_context.py` — 构建设备上下文
- `scripts/build_handoff.py` — 构建交接数据
- `scripts/run.sh` — 薄壳入口

### 8K 系列数据工具（旋转机组）
- `scripts/device_analysis.py` — 设备树分析
- `scripts/get_trend_data_tool.py` — 获取趋势数据
- `scripts/extract_trend_features_tool.py` — 提取趋势特征
- `scripts/get_waveform_data_tool.py` — 获取波形数据
- `scripts/get_orbit_data_tool.py` — 获取轴心轨迹数据
- `scripts/extract_spectral_waveform_features_tool.py` — 提取频谱波形特征
- `scripts/extract_orbit_centerline_features_tool.py` — 提取轴心轨迹中心线特征
- `scripts/extract_s_trend_features_tool.py` — 提取 S 系列趋势特征

## Dependencies

- `features-tool` skill — 提供 `ins/` (InS API 客户端)、`agents/` (function_tool)、诊断规则等公共模块
- 工具脚本通过 sys.path 引用 features-tool 的模块

## Notes

- `--access-token` is no longer required; the token is injected via `INS_ACCESS_TOKEN` env var
