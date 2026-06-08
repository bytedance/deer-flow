## Why

`data-analyst` skill 承载了日报、周报、月报、趋势分析、故障诊断、失效分析、闭环管理、巡检等 8 类功能共 30+ 脚本，单一 skill 边界模糊、脚本互相耦合（共享 `_report_common` / `_data_providers` / `_ins_provider` 等内部模块），修改任一报告类型都需要评估对其他报告的影响。将其拆分为三个独立 skill 可消除耦合、简化维护、让每个报告类型独立演进。

## What Changes

- **新建三个 skill**：`daily-report`、`weekly-report`、`monthly-report`，各自包含该报告类型专属的查询脚本、KPI 计算脚本、导出脚本及所需的内部模块
- **每个 skill 自包含全部依赖**：`_data_providers.py`、`_data_provider_impls.py`、`_platform_bridge.py`、`_ins_provider.py`、`_report_common.py` 等内部模块各自独立复制，skill 之间零代码共享
- **精简每个 skill 的脚本集**：只保留该报告类型实际需要的脚本，日/周/月报分别只需 5-6 个脚本（查询 + KPI + 导出 + 设备列表 + 内部模块）
- **重构 `_report_common.py`**：当前 400+ 行包含了所有三种报告的常量和工具函数，拆分后各自只保留本报告类型需要的部分
- **重构 `_data_provider_impls.py`**：当前包含 8 个数据源的 Provider，拆分后各自只注册 daily/weekly/monthly 对应的 Provider
- **重构 `report_scripts.yaml`**：每个 skill 独立声明自己的脚本注册表
- **重构 SKILL.md**：每个 skill 独立描述自己的脚本用法
- **更新 DSL 模板引用**：`daily-equipment` / `weekly-equipment` / `monthly-equipment` 模板中的 `name: data-analyst/xxx` 改为 `name: daily-report/xxx` 等
- **更新 Agent SOUL.md**：`ai-report--daily` / `ai-report--weekly` / `ai-report--monthly` 中的脚本路径引用
- **保留原 `data-analyst` skill**：趋势分析、故障诊断、失效分析、闭环、巡检等功能继续留在 `data-analyst` 中（或后续再拆）
- **删除已移除的功能**：Pro/Ultra 级脚本已在之前删除，不再纳入新 skill
- Mark breaking changes with **BREAKING**：DSL 模板中 `data-analyst/query_daily` 等脚本引用改为 `daily-report/query_daily`；Agent SOUL.md 中 `/mnt/skills/custom/data-analyst/scripts/` 路径改为 `/mnt/skills/custom/daily-report/scripts/` 等

## Capabilities

### New Capabilities
- `daily-report-skill`: 日报独立 skill，包含 query_daily / daily_kpi / list_equipment / export_report 及所需内部模块，通过 DSL 模板 `daily-equipment` 驱动
- `weekly-report-skill`: 周报独立 skill，包含 query_weekly / weekly_kpi / list_equipment / export_report 及所需内部模块，通过 DSL 模板 `weekly-equipment` 驱动
- `monthly-report-skill`: 月报独立 skill，包含 query_monthly / monthly_kpi / list_equipment / export_report 及所需内部模块，通过 DSL 模板 `monthly-equipment` 驱动

### Modified Capabilities
- `equipment-report-data-provider`: DSL 模板中脚本命名空间从 `data-analyst/` 变更为 `daily-report/` / `weekly-report/` / `monthly-report/`
- `dsl-provider-field`: 同上，模板 `default.yaml` 中 `name:` 字段值变更

## Impact

- **Affected code**:
  - `skills/custom/data-analyst/` — 保留非日报/周报/月报的脚本，移除 report 相关脚本
  - `skills/custom/daily-report/` — 新建
  - `skills/custom/weekly-report/` — 新建
  - `skills/custom/monthly-report/` — 新建
  - `agents/builtin/report-templates/daily-equipment/default.yaml` — `name:` 引用更新
  - `agents/builtin/report-templates/weekly-equipment/default.yaml` — `name:` 引用更新
  - `agents/builtin/report-templates/monthly-equipment/default.yaml` — `name:` 引用更新
  - `agents/builtin/ai-report--daily/SOUL.md` — 脚本路径更新
  - `agents/builtin/ai-report--weekly/SOUL.md` — 脚本路径更新
  - `agents/builtin/ai-report--monthly/SOUL.md` — 脚本路径更新
  - `backend/packages/harness/deerflow/report_templates/` — Script Registry 加载逻辑可能需要适配新命名空间
- **Breaking changes**: DSL 模板和 Agent SOUL.md 中的脚本命名空间从 `data-analyst/` 变更为 `daily-report/` / `weekly-report/` / `monthly-report/`
