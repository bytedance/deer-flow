## Context

当前 `skills/custom/data-analyst/` 是一个单一 skill，承载了 8 类功能（日报/周报/月报/趋势分析/故障诊断/失效分析/闭环/巡检）共 30+ 脚本。内部模块（`_data_providers.py`、`_report_common.py`、`_platform_bridge.py`、`_ins_provider.py`）被所有脚本共享，修改任何一个常量或 Provider 注册逻辑都会影响所有报告类型。

目标：拆分为三个完全独立的 skill，每个 skill 自包含全部依赖，零跨 skill 代码共享。

**约束：**
- 脚本运行在 Docker sandbox 容器中，通过 `/mnt/skills/custom/<skill-name>/scripts/` 路径访问
- DSL 模板通过 `name: <skill>/<script>` 引用脚本（Script Registry 解析）
- Agent SOUL.md 直接通过绝对路径调用 Python 脚本
- 三个 skill 不能互相依赖，各自可独立安装/卸载/升级

## Goals / Non-Goals

**Goals:**
- 创建 `daily-report`、`weekly-report`、`monthly-report` 三个独立 skill
- 每个 skill 包含完整的自包含脚本集（查询 + KPI 计算 + 导出 + 设备列表 + 所有内部模块）
- 从 `data-analyst` 中移除日报/周报/月报相关脚本
- 更新 DSL 模板引用、Agent SOUL.md 路径和 Script Registry 配置
- 精简 `_report_common.py`：每个 skill 只保留自己需要的常量/函数
- 精简 `_data_provider_impls.py`：每个 skill 只注册自己需要的 Provider
- 精简 `export_report.py`：每个 skill 只处理自己的报告类型

**Non-Goals:**
- 不修改 `_platform_bridge.py` 和 `_ins_provider.py` 的业务逻辑（纯复制）
- 不修改趋势分析/故障诊断/失效分析/闭环/巡检功能（留在原 `data-analyst` skill）
- 不修改后端 Script Registry 加载机制
- 不修改 GenUI 组件或前端渲染逻辑
- 不修改 KPI 聚合算法或阈值

## Decisions

### D1: 完全自包含 — 每个 skill 拥有所有内部模块的独立副本

**选型：** 三个新 skill 各自包含 `_data_providers.py`、`_data_provider_impls.py`、`_platform_bridge.py`、`_ins_provider.py`、`_report_common.py`、`export_report.py`、`list_equipment.py` 的独立副本。

**理由：** 这是满足"相互独立、互不影响"要求的唯一方式。虽然会导致 ~5000 行代码在三处重复，但这些内部模块高度稳定（近两周只有 platform bridge 有一次修改），维护成本远低于跨 skill 耦合带来的风险。每个 skill 的修改范围严格限定在自身目录内。

**替代方案：** 将共享模块提取到 `skills/custom/_shared/` 并让三个 skill 通过 `sys.path` 引用。被拒绝，因为这引入了跨 skill 依赖。

### D2: 每个 skill 只保留自己需要的常量/函数/Provider

**选型：** 从 `_report_common.py` 中只保留该报告类型需要的 KPI 常量、校验函数、聚合函数。从 `_data_provider_impls.py` 中只注册该报告类型的 Provider。从 `export_report.py` 中只保留该报告类型的渲染/导出逻辑。

**理由：** 精简后的文件更小、更易理解。开发者在修改日报时不会被周报/月报的代码干扰。

**拆分细节：**

| 模块 | daily-report 保留 | weekly-report 保留 | monthly-report 保留 |
|------|------------------|-------------------|---------------------|
| `_report_common.py` | KPI_DISPLAY_NAMES (不含 monthly 扩展), KPI_BETTER_WHEN_HIGHER, KPI_THRESHOLDS, validate_equipment_ids, parse_csv, error_output, load_sibling_module, detect_equipment_type, resolve_equipment_by_scope, direction, safe_pct | 同上 + has_previous_year_data_weekly, aggregate_kpis (7-day 均值) | 同上 + KPI_DISPLAY_NAMES_MONTHLY, KPI_BETTER_WHEN_HIGHER_MONTHLY, parse_report_month, month_bounds, has_previous_year_data_monthly, aggregate_kpis |
| `_data_provider_impls.py` | PlatformDailyProvider only | PlatformWeeklyProvider only | PlatformMonthlyProvider only |
| `export_report.py` | render_markdown (daily), write_report (daily only) | render_markdown (weekly), write_report (weekly only) | render_markdown (monthly), write_report (monthly only) |

### D3: 不改变脚本的内部 API 和 CLI 参数

**选型：** `query_daily.py`、`daily_kpi.py` 等脚本的 CLI 接口（argparse 参数）和输出 JSON schema 保持完全不变。

**理由：** Agent SOUL.md 和 DSL 模板中的脚本调用参数是稳定的契约。只改 skill 命名空间，不改脚本行为。

### D4: 保留原 `data-analyst` skill 承载非报表功能

**选型：** 趋势分析、故障诊断、失效分析、闭环管理、巡检等功能留在 `data-analyst` 中不迁移。

**理由：** 这些功能与日报/周报/月报无耦合，各自独立。保持不动可以最小化本次变更范围。待后续需要时再独立拆分。

## File Inventory Per Skill

### daily-report

```
skills/custom/daily-report/
├── SKILL.md                              # 日报专属文档
├── report_scripts.yaml                   # 日报脚本注册表
└── scripts/
    ├── _data_providers.py                # 完整副本（所有 Protocol + registry + fetch_with_fallback）
    ├── _data_provider_impls.py           # 精简：仅 PlatformDailyProvider
    ├── _platform_bridge.py               # 完整副本
    ├── _ins_provider.py                  # 完整副本
    ├── _report_common.py                 # 精简：daily 所需常量/函数
    ├── query_daily.py                    # 不变
    ├── daily_kpi.py                      # 不变
    ├── list_equipment.py                 # 完整副本
    └── export_report.py                  # 精简：仅 daily 类型
```

### weekly-report

```
skills/custom/weekly-report/
├── SKILL.md
├── report_scripts.yaml
└── scripts/
    ├── _data_providers.py                # 完整副本
    ├── _data_provider_impls.py           # 精简：仅 PlatformWeeklyProvider
    ├── _platform_bridge.py               # 完整副本
    ├── _ins_provider.py                  # 完整副本
    ├── _report_common.py                 # 精简：weekly 所需常量/函数
    ├── query_weekly.py                   # 不变
    ├── weekly_kpi.py                     # 不变
    ├── list_equipment.py                 # 完整副本
    └── export_report.py                  # 精简：仅 weekly 类型
```

### monthly-report

```
skills/custom/monthly-report/
├── SKILL.md
├── report_scripts.yaml
└── scripts/
    ├── _data_providers.py                # 完整副本
    ├── _data_provider_impls.py           # 精简：仅 PlatformMonthlyProvider
    ├── _platform_bridge.py               # 完整副本
    ├── _ins_provider.py                  # 完整副本
    ├── _report_common.py                 # 精简：monthly 所需常量/函数
    ├── query_monthly.py                  # 不变
    ├── monthly_kpi.py                    # 不变
    ├── list_equipment.py                 # 完整副本
    └── export_report.py                  # 精简：仅 monthly 类型
```

### data-analyst（保留内容）

```
skills/custom/data-analyst/
├── SKILL.md                              # 更新：移除日报/周报/月报文档
├── diagnosis_kind_config.yaml            # 不变
├── report_scripts.yaml                   # 更新：移除 daily/weekly/monthly 条目
└── scripts/
    ├── _data_providers.py                # 不变
    ├── _data_provider_impls.py           # 更新：移除 PlatformDaily/Weekly/MonthlyProvider
    ├── _platform_bridge.py               # 不变
    ├── _ins_provider.py                  # 不变
    ├── _report_common.py                 # 不变（保留完整版供 trend/diagnosis/failure 使用）
    ├── _stub_helpers.py                  # 不变
    ├── _model_loader.py                  # 不变
    ├── query_trend.py                    # 不变
    ├── trend_analysis.py                 # 不变
    ├── trend_report_transform.py         # 不变
    ├── query_diagnosis.py                # 不变
    ├── diagnosis_features.py             # 不变
    ├── diagnosis_analysis.py             # 不变
    ├── diagnosis_report_transform.py     # 不变
    ├── query_fault_context.py            # 不变
    ├── query_failure_data.py             # 不变
    ├── failure_analysis.py               # 不变
    ├── build_fault_timeline.py           # 不变
    ├── query_closure_items.py            # 不变
    ├── closure_summary.py                # 不变
    ├── query_inspection.py               # 不变
    ├── inspection_summary.py             # 不变
    ├── inspection_attachment_summary.py  # 不变
    ├── data_quality.py                   # 不变
    ├── export_diagnosis_report.py        # 不变
    ├── list_datasets.py                  # 不变
    ├── fetch_dataset.py                  # 不变
    ├── preview_dataset.py                # 不变
    └── requirements.txt                  # 不变
```

### data-analyst 移除的脚本（已迁到新 skill）

- `query_daily.py`、`daily_kpi.py` → `daily-report/`
- `query_weekly.py`、`weekly_kpi.py` → `weekly-report/`
- `query_monthly.py`、`monthly_kpi.py` → `monthly-report/`
- `list_equipment.py` → 三个 skill 各一份副本
- `export_report.py` → 三个 skill 各一份精简副本

## Risks / Trade-offs

- **[代码重复]** 三个 skill 各有 `_platform_bridge.py`（~400 行）、`_ins_provider.py`（~1300 行）、`_data_providers.py`（~400 行）的完整副本 → 修复 bug 时需要三处同步修改。缓解：这些模块高度稳定，且三个 skill 独立演进意味着修改通常只需要在一个 skill 中进行。
- **[Skill 安装体积]** 三个 skill 各自包含完整依赖，总体积约 3x → 缓解：Python 脚本体积小（总计 ~200KB），不影响容器启动和运行性能。
- **[DSL 模板引用变更]** 为 **BREAKING** 变更 → 缓解：与拆分同步更新，一次性完成。
- **[Agent SOUL.md 路径变更]** 脚本绝对路径从 `/mnt/skills/custom/data-analyst/scripts/` 变为 `/mnt/skills/custom/daily-report/scripts/` 等 → 缓解：同步更新三个 SOUL.md。

## Migration Plan

1. 创建三个新 skill 目录及完整脚本集
2. 更新三个 DSL 模板 `default.yaml` 中的 `name:` 引用
3. 更新三个 Agent SOUL.md 中的脚本路径
4. 从 `data-analyst` 中移除已迁移脚本
5. 更新 `data-analyst/report_scripts.yaml` 移除 daily/weekly/monthly 条目
6. 更新 `data-analyst/SKILL.md` 移除日报/周报/月报文档
7. 部署测试：分别触发日报/周报/月报 DSL 链路验证完整流程

**回滚策略：** Git revert 整个 commit，恢复原 `data-analyst` skill 结构。
