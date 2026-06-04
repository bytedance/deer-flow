---
name: monitoring-analysis
description: >
  监测分析专属 Skill。提供特征提取、异常判定、阈值判定和报告导出能力。
  配合 monitoring-data Skill（数据获取）使用，由监测分析 Agent 编排调用。
---

# Monitoring Analysis Skill Scripts

本 Skill 提供监测分析专属脚本：特征提取、异常判定、报告导出。

## When to Use This Skill

当监测分析 Agent 获取到原始监测数据后，调用本 Skill 进行：
- 特征提取（趋势特征 + 波形频谱特征）
- 异常判定（趋势异常 + 阈值越限 + 频谱异常）
- 报告导出（Markdown / PDF）

## Preconditions

- 已由 `monitoring-data` Skill 获取到 `monitoring_data.json`
- 环境变量 `MONITORING_OUTPUT_DIR` — 输出目录（默认 `/mnt/user-data/outputs`）

## Scripts

### extract_monitoring_features.py — 特征提取 + 异常判定 [新]

```bash
python /mnt/skills/custom/monitoring-analysis/scripts/extract_monitoring_features.py \
  --input /mnt/user-data/outputs/monitoring_data.json \
  --analysis-focus full \
  --output-dir /mnt/user-data/outputs/
```

**参数**：
| 参数 | 说明 |
|------|------|
| `--input` | monitoring_data.json 路径（由 monitoring-data Skill 产出） |
| `--analysis-focus` | `full`(默认) / `trend` / `anomaly` / `spectrum` |
| `--output-dir` | 输出目录 |

**输出**：`monitoring_features.json`，包含每个测点的 trend_features、spectral_features、anomalies、health_status。

### _thresholds.py — 阈值配置 [新，内部模块]

10 个测点类别的 warning/critical 阈值。被 `extract_monitoring_features.py` 导入使用。

覆盖类别：vib, vibc, process_6k, thickness, probe, leak, key, speed。

### export_report.py — 报告导出

```bash
python /mnt/skills/custom/monitoring-analysis/scripts/export_report.py \
  --input /mnt/user-data/outputs/monitoring_features.json \
  --report-type monitoring \
  --format md
```

支持 daily/weekly/monthly/monitoring 四种 report_type。

---

## Deprecated Scripts（旧版，后续不再使用）

以下脚本保留用于向后兼容，新流程不再调用：

- `query_trend.py` — 旧版趋势数据查询（已被 monitoring-data Skill 替代）
- `trend_analysis.py` — 旧版趋势分析（已被 extract_monitoring_features.py 替代）
- `data_quality.py` — 旧版数据质量评估
- `_ins_provider.py` — 旧版 InS 适配器（已被 monitoring-data Skill 替代）
- `_data_providers.py` — 旧版数据提供者抽象
- `_platform_bridge.py` — 旧版平台桥接

## Output Convention

- 所有脚本输出 JSON 文件到 `--output-dir` 指定目录
- 错误信息输出到 stderr，不阻塞 Agent 主流程
- 认证通过环境变量（INS_ACCESS_TOKEN），不硬编码

## Dependencies

- **monitoring-data Skill** — 提供 `monitoring_data.json` 作为输入
- **不依赖 features-tool** — 特征提取算法内联实现
