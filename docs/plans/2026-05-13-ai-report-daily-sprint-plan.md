# AI 日报智能体 Sprint 实施计划

> **来源设计文档**：[AI 日报智能体功能设计文档](./2026-05-13-ai-report-daily-design.md)
> **范围**：基于设计文档拆分出的执行计划，覆盖 Sprint 目标、故事拆分、依赖、验收标准、风险与排期。

---

## 1. Sprint Goal

在不新增后端路由、不新增前端组件的前提下，完成 `ai-report--daily` 的日报生成 MVP：用户可通过 GenUI 表单选择日报参数，基于演示/Skill 数据生成 KPI、趋势图、异常表和 Markdown 总结，并验证导出链路的可行性。

## 2. Sprint 假设

| 项 | 假设 |
| ---- | ------ |
| Sprint 周期 | 1 周 |
| 团队配置 | 1 名全栈/Agent 工程师 |
| 可用容量 | 5 人天 |
| 缓冲 | 20%（约 1 人天） |
| 可承诺容量 | 4 人天 |
| Must 承诺范围 | Stories 1-5：SOUL.md 改造、演示数据、KPI 计算、GenUI 渲染、Markdown 导出 |
| Should / Stretch 范围 | Story 6 PDF 依赖验证、Story 7 完整测试补齐 |
| 本 Sprint 目标 | 完成 SOUL.md 改造 + Markdown 导出 MVP，不强行接真实数据源，不承诺 PDF 完整交付 |

> 真实数据接入依赖 MCP / HTTP API 定稿，建议放到下一 Sprint 或作为并行外部依赖推进。
> 当前 sandbox 镜像未确认包含 `pandoc` / `wkhtmltopdf`，PDF 在本 Sprint 只做依赖验证和方案决策。

---

## 3. Stories

> **承诺口径**：Must Stories（1-5，共 14 SP）是本 Sprint 的交付承诺；Should Stories（6-7，共 4 SP）在 Must 完成后推进，不阻塞 MVP 验收。

### Story 1（Must）：改写 `ai-report--daily` SOUL.md（3 SP）

**目标**：让日报智能体遵循现有 `monitoring-analysis` 模式：数据源发现 → render_ui 表单 → ui_interaction → 数据拉取 → GenUI 输出。

**范围**：

- 更新 `agents/builtin/ai-report--daily/SOUL.md`
- 加入 MCP / Skill / http_connector / 静态回退优先级链
- 加入 `daily-report-params` 参数表单
- 加入 `daily-report-export` 导出表单
- 明确 STOP 行为，避免表单发送后继续生成假数据
- 明确从 `payload` 顶层读取字段值（不是 `values`），与 `genui_middleware` 实际回传结构一致

**验收标准**：

- 用户进入日报智能体后，先看到参数表单
- 表单包含日期、设备范围、KPI、对比基准
- 提交表单后才进入数据拉取和报告生成
- SOUL.md 中 ui_interaction 处理段落明确引用 `payload.<field>`
- 无后端/前端代码变更

**依赖**：GenUI `form` 可用；`data-analyst` skill 启用。

### Story 2（Must）：新增 `query_daily.py` 演示数据查询脚本（3 SP）

**目标**：提供稳定的演示数据源，让日报流程在真实数据 API 未确定前可以端到端跑通。

**范围**：

- 新增 `skills/custom/data-analyst/scripts/query_daily.py`
- 支持 `--date`、`--equipment`、`--kpis`、`--compare`
- 输出 `/mnt/user-data/outputs/daily_data.json`
- 返回 `current` / `compare` / `alarms` 数据结构

**验收标准**：

- 命令可在 sandbox 中执行
- 无真实 API 时返回演示数据
- 支持前一日 / 上周同日 / 不对比
- 输出 JSON 符合设计文档 §6.1

**依赖**：`/mnt/user-data/outputs/` 可写；`skills/custom/data-analyst/scripts/` 路径存在。

### Story 3（Must）：新增 `daily_kpi.py` KPI 计算脚本（3 SP）

**目标**：将原始日报数据转换成 GenUI 可直接消费的数据结构。

**范围**：

- 新增 `skills/custom/data-analyst/scripts/daily_kpi.py`
- 读取 `/mnt/user-data/outputs/daily_data.json`
- 输出 `/mnt/user-data/outputs/daily_kpi.json`
- 生成 `kpi_summary`、`trend_chart`、`alarm_table`、`overall_status`

**验收标准**：

- KPI delta / trend 计算正确
- `previous_day` 与 `previous_week` 对比路径都被覆盖
- `compare=none` 或 compare 为空时显示 `None` / `—`，不报错
- 告警表为空时返回空数组
- 输出 JSON 符合设计文档 §6.2

**依赖**：Story 2 输出结构稳定。

### Story 4（Must）：GenUI 日报渲染联调（3 SP）

**目标**：验证 SOUL.md 能够基于脚本输出渲染标准日报页面。

**范围**：

- 验证 `card`、`echart`、`table`、`markdown`、`form` 组件调用
- 验证参数表单 → 数据脚本 → KPI 脚本 → GenUI Block 的完整链路

**验收标准**：

- 生成概览卡片
- 生成 KPI 卡片
- 生成 24 小时趋势图
- 生成异常事件表
- 生成总结与建议 Markdown
- 页面无 GenUI schema 错误

**依赖**：Story 1、2、3。

### Story 5（Must）：Markdown 导出 MVP（2 SP）

**目标**：先完成 Markdown 导出，PDF 只做环境验证和技术预留。

**范围**：

- 新增 `skills/custom/data-analyst/scripts/export_report.py`
- 支持 `--format md`
- 输出 `/mnt/user-data/outputs/daily_report.md`
- 通过 artifact URL 下载
- 在 SOUL.md 中处理 `callback_id=daily-report-export` 的二次表单回调

**验收标准**：

- Markdown 文件生成成功
- 文件位于 `/mnt/user-data/outputs/`
- 前端可通过 artifact URL 下载
- 报告内容包含概览、KPI、异常、建议
- SOUL.md 收到 `daily-report-export` 回调后调用 export 脚本并通过 `render_ui markdown` 返回下载链接

**依赖**：Story 3 输出结构稳定；artifact 下载链路可用。

### Story 6（Should）：PDF 依赖验证与风险决策（1 SP）

**目标**：确认 PDF 导出是否能在当前 sandbox 环境落地，避免 Sprint 内被依赖阻塞。

**范围**：

- 验证 `pandoc --version`
- 验证 `wkhtmltopdf --version`
- 验证 Python `md2pdf` 是否可用
- 结合当前 sandbox Dockerfile 现状输出结论：优先纯 Python 回退 / 修改 sandbox 镜像 / PDF 延后到下一 Sprint

**验证记录（2026-05-13）**：

| 依赖 | 探测结果 | 结论 |
| ---- | -------- | ---- |
| `pandoc --version` | `command not found` | 当前环境不可用 |
| `wkhtmltopdf --version` | `command not found` | 当前环境不可用 |
| Python `md2pdf` | `False` | 当前后端 venv 未安装 |
| Python `weasyprint` | `False` | 当前后端 venv 未安装 |
| Python `xhtml2pdf` | `False` | 当前后端 venv 未安装 |
| Python `pypandoc` | `False` | 当前后端 venv 未安装 |

**风险决策**：本 Sprint 不交付 PDF 导出，继续仅承诺 Markdown MVP。PDF 如进入下一 Sprint，优先方案是更新 sandbox 镜像并显式安装 `pandoc` / `wkhtmltopdf` / 中文字体；若希望纯 Python 路径，需要先评估 `weasyprint` 或 `xhtml2pdf` 的中文字体、表格分页和运行时依赖。

**验收标准**：

- 明确 PDF 方案是否可行
- 若不可行，记录需要的镜像依赖（pandoc、wkhtmltopdf、中文字体等）
- 给出是否采用 `md2pdf` 作为 MVP 回退路径的决策
- 不影响 Markdown MVP 交付

**依赖**：sandbox 环境可访问。

### Story 7（Should）：单元测试与最小回归验证（3 SP）

**目标**：确保新增 Skill 脚本稳定，避免 prompt 流程依赖脆弱脚本。

**范围**：

- 为 `query_daily.py` 增加参数解析 / 演示数据生成测试
- 为 `daily_kpi.py` 增加 KPI delta / trend / 空数据测试
- 为 `export_report.py` 增加 Markdown 渲染测试
- 增加数据契约测试，确保 `query_daily.py` 输出可被 `daily_kpi.py` 直接消费
- 可选：增加路径校验，确保输出在 `/mnt/user-data/outputs/`

**验收标准**：

- Python 测试通过
- 关键脚本可单独执行
- `query_daily.py` 输出 JSON 符合设计文档 §6.1
- `daily_kpi.py` 输出 JSON 符合设计文档 §6.2
- 契约测试覆盖 query → kpi → export 的最小链路
- 无硬编码真实凭据
- 错误输出为结构化 JSON 或明确 stderr

**依赖**：Story 2、3、5。

---

## 4. 不建议本 Sprint 承诺的内容

### 真实数据接入

**原因**：`data_catalog` MCP 当前只是协议规范，尚未注册；`http_connector` 具体 connector 名称、参数、认证方式未明确；KPI 口径需要业务确认。

**建议**：本 Sprint 只保留接口形状和演示回退，下个 Sprint 单独做真实数据接入。

### PDF 完整交付

**原因**：依赖 sandbox 镜像是否包含 `pandoc` / `wkhtmltopdf`；中文 PDF 字体、分页、表格样式通常需要额外调试。

**建议**：本 Sprint 只完成 Markdown 导出 + PDF 环境验证；若环境具备，再作为 stretch goal 完成 PDF。

### 周报/月报模板复用

**原因**：日报 MVP 尚未稳定，过早抽象会放大返工成本。

**建议**：等日报脚本和数据契约稳定后再抽公共模板。

---

## 5. Sprint Sequencing

```text
Day 1
- 改写 ai-report--daily/SOUL.md
- 新增 query_daily.py 演示数据脚本

Day 2
- 新增 daily_kpi.py
- 完成 KPI / 趋势 / 异常表结构
- 写脚本级单元测试

Day 3
- 联调 GenUI：form → ui_interaction → 脚本 → card/echart/table/markdown
- 修正 SOUL.md 中 render_ui 参数和输出格式

Day 4
- 新增 export_report.py
- 完成 Markdown 导出
- 验证 artifact 下载链路

Day 5
- PDF 环境验证
- 回归测试
- 修复问题
- 整理交付说明
```

---

## 6. Sprint Summary

```text
Sprint Goal:
完成 AI 日报智能体 MVP，使其通过 GenUI 表单收集参数，基于 Skill 脚本生成日报，并支持 Markdown 导出。

Duration:
1 周

Team Capacity:
5 人天，预留 20% 缓冲后约可承诺 4 人天 / 14 SP

Must Stories（承诺，共 14 SP）:
1. 改写 ai-report--daily SOUL.md — 3 SP
2. 新增 query_daily.py 演示数据脚本 — 3 SP
3. 新增 daily_kpi.py KPI 计算脚本 — 3 SP
4. GenUI 日报渲染联调 — 3 SP
5. Markdown 导出 MVP — 2 SP

Should / Stretch Stories（容量允许时推进，共 4 SP）:
6. PDF 依赖验证 — 1 SP
7. 单元测试与最小回归验证 — 3 SP

不承诺范围:
- PDF 完整交付（依赖 sandbox 镜像决策）
- 真实数据接入（依赖 MCP / HTTP API 定稿）
- 周报 / 月报模板复用（待日报契约稳定）
```
