# 报告模板平台 (Report Template Platform)

DSL 驱动的报告生成系统：用户用 YAML 描述报告（表单、数据步骤、转换、章节、导出），运行时通过 GenUI 收集输入，在白名单脚本内执行，输出 `report_payload.json` + Markdown/PDF 制品。

完整设计文档: [docs/plans/2026-05-14-ai-report-custom-template-design.md](../plans/2026-05-14-ai-report-custom-template-design.md)

## 模块结构

```text
report_templates/
├── schema.py                  # DSL v1 Pydantic schema (form_steps, data_steps, transforms, sections, export)
├── validator.py               # 交叉引用 / JSONPath / 脚本注册表 / 章节类型检查
├── source_resolver.py         # JSONPath 子集（白名单: root / field / array-all; depth ≤ 8）
├── script_registry.py         # 从每个启用的技能加载 `report_scripts.yaml`
├── repository.py              # FileSystemReportTemplateRepository (etag + 原子重命名 + fcntl)
├── records.py                 # ReportTemplate / ReportTemplateVersion / ReportRun Pydantic 模型
├── permissions.py             # private/tenant/builtin 矩阵，复用 superadmin/tenant_admin
├── service.py                 # 路由 + 工具使用的跨切面编排
├── push_block.py              # 从工具实现流式 GenUI 块的辅助函数
├── generic_renderer.py        # sections → Markdown (必须) + ECharts SVG (PDF 回退)
└── runtime/
    ├── state.py               # status.json 状态机 + 步骤转换检查
    ├── step_renderer.py       # form_step + before_step → GenUI 表单块
    ├── step_submitter.py      # 表单载荷验证 + 分发
    ├── data_runner.py         # 子进程白名单执行；输出到 run-scoped 目录
    ├── payload_builder.py     # 从章节组装 report_payload.json
    ├── report_renderer.py     # sections → 通过 get_stream_writer 推送的 GenUI 块
    └── exporter.py            # 调用 export_report.py 生成 .md (必须) / .pdf (可选)
```

## LLM 驱动运行时

运行时**不是**后台 worker —— 它是 14 个内置工具的集合，`ai-report--custom` Agent 在 SOUL 引导下按顺序调用。

**跨工具状态**: 存储在 `{run_output_dir}/status.json`
- 每个工具在执行前验证 `report_run_id` + `expected_step`
- 不匹配返回 `STATE_MISMATCH`，防止 LLM 漂移

## 工具清单

### 模板管理工具 (`tools/builtins/report_template_tools.py`)

| 工具 | 职责 |
|------|------|
| `report_template_list` | 列出可见模板 |
| `report_template_get` | 获取模板详情 |
| `report_template_validate` | 验证 DSL |
| `report_template_save_draft` | 保存草稿 |
| `report_template_publish` | 发布新版本 |
| `report_template_fork` | Fork 模板 |

### 运行时工具 (`tools/builtins/report_template_runtime_tools.py`)

| 工具 | 职责 |
|------|------|
| `report_template_prepare_run` | 准备运行环境 |
| `report_template_render_step` | 渲染表单步骤 |
| `report_template_submit_step` | 提交表单步骤 |
| `report_template_run_data_steps` | 执行数据步骤 |
| `report_template_assemble_payload` | 组装报告载荷 |
| `report_template_render_report` | 渲染报告 |
| `report_template_export` | 导出报告 |
| `report_template_resume_run` | 恢复运行 |

**工具设计原则**: 薄壳（≤50 行/个），解包参数 → 调用 `runtime/` 模块 → 包装错误。`user_id` / `tenant_id` 始终来自 auth 上下文，**永不**来自请求体或 LLM 参数。

## 存储结构

### 用户/租户模板（可写）

路径: `{DEER_FLOW_HOME}/report-templates/{users|tenants}/{owner_id}/{template_id}/`

```
{template_id}/
├── template.json              # 元数据 + etag
├── versions/
│   └── v{N}.json              # 不可变快照（包含 parsed `dsl` 和 original `dsl_yaml`）
└── runs/
    └── {report_run_id}.json   # 轻量索引（载荷 + 制品在线程下）
```

### 内置模板（只读，版本控制）

路径: `agents/builtin/report-templates/{template-name}/{default.yaml,metadata.yaml}`

- 启动时加载到内存索引
- API 不可写 —— 通过代码 PR + 重启修改

### 运行范围输出

路径: `{thread_output_dir}/report-runs/{report_run_id}/`

```
{report_run_id}/
├── parameters.json            # 用户输入参数
├── template_version.json      # 使用的模板版本快照
├── status.json                # 运行状态机
├── data/
│   └── *.json                 # 数据步骤输出
├── report_payload.json        # 组装后的报告载荷
└── exports/
    ├── report.md              # Markdown 报告（必须）
    └── report.pdf             # PDF 报告（可选）
```

**生命周期**: 线程是生命周期根。删除线程同时删除其 ReportRun 索引和输出。

## 并发与安全

### 原子写入

- 所有写操作: 临时文件 + 原子重命名
- `expected_etag` 乐观锁，不匹配返回 409
- fcntl / Windows 回退跨进程锁
- `index.json` 在同一锁下更新

### ID 验证

- `template_id`: `^tpl_[A-Z0-9]{20,32}$`
- `report_run_id`: `^rr_[A-Z0-9]{20,32}$`
- 所有路径通过 `Path.resolve()` + `relative_to()` 包含检查

## 脚本注册表 (Skill-Contributed)

每个技能可发布 `report_scripts.yaml` 在根目录。

**注册表行为**:
- 扫描启用的技能
- 暴露脚本名为 `{skill_name}/{script_name}` (如 `daily-report/query_daily`)
- DSL `data_steps[].name` 必须使用限定名
- `ScriptDescriptorYaml` 支持 `args_aliases: dict[str, dict[str, str]]` 翻译短 DSL 名到规范脚本枚举值

## 章节组件

| 组件 | 说明 |
|------|------|
| `markdown` | Markdown 文本 |
| `card` | 单卡片 |
| `card_group` | 卡片组 |
| `echart` | ECharts 图表 |
| `table` | 数据表格 |
| `image` | 图片 |

**验证器警告**: 当 `section.source` 尾部不像组件期望的载荷时发出警告（如 `echart` 应指向以 `chart`/`option` 结尾的内容）。

## 内置模板

已发布:
- `daily-equipment` - 设备日报
- `weekly-equipment` - 设备周报
- `monthly-equipment` - 设备月报
- `trend-equipment` - 设备趋势
- `diagnosis-fault` - 故障诊断
- `failure-analysis` - 故障分析
- `closure-summary` - 结单总结
- `inspection` - 巡检报告

CI 测试 `tests/test_builtin_report_templates.py` 验证每个 `agents/builtin/report-templates/*/default.yaml`。

## 解释性报告 (§13.2)

trend / diagnosis / failure-analysis 存根转换输出:
- `findings[]` - 发现
- `evidence[]` - 证据（含 `source_type`, `source_id`, `snapshot_path`, `checksum`, `time_range`, `retrieved_at`）
- `confidence` - 置信度
- `assumptions[]` - 假设
- `data_coverage` - 数据覆盖
- `human_review_required: true` - 需要人工审核

## 导出

- **Markdown**: 必须（失败 = ReportRun 失败）
- **PDF**: 可选（`weasyprint` ImportError 被捕获，记录 `pdf_skipped_reason = "weasyprint_unavailable"`）

## ai-report--daily 回退

DSL 路径优先；硬编码 SOUL.md 路径作为回退（在 `report_template_*` 错误 / 缺失内置 / 禁用技能 / 验证器回退时触发）。

`ai-report--custom` 和任何从头创建的 Agent **没有回退** —— 平台宕机时直接失败。

## 直接报告执行器 (Direct Report Executor)

**模块**: `packages/harness/deerflow/report_executor/`

Agent 通过 `config.yaml` 的 `executor_type` 字段声明执行策略：
- `executor_type: direct` → 直接执行路径
- `executor_type: dsl` 或省略 → DSL 模板引擎（默认）

### 组件

| 组件 | 说明 |
|------|------|
| `executor.py` | `DirectReportExecutor` 类，编排脚本执行 (`query_*.py` → `*_kpi.py` → `export_report.py`) |
| `report_direct_execute` 工具 | LangChain 工具包装器，返回 `{report_run_id, artifacts, status}` 或 `{error: {code, message, step}, status: "failed"}` |
| `router.py` | `get_report_tools_for_agent(agent_config)` 读取 `executor_type`，返回对应工具 |

### stdout 契约

每个脚本将实际数据写入自己的输出文件（例如 `daily_data.json`、`daily_kpi.json`、`daily_report.md`），并仅向 stdout 打印一条元数据信封：

```json
{"output": "/mnt/user-data/outputs/daily_data.json", "report_date": "2026-06-11"}
```

`DirectReportExecutor._resolve_output_path` 解析该 `output` 字段定位真实数据文件，**不会**将 stdout 内容覆写到数据文件。若 `output` 字段缺失或指向的文件不存在，则使用回退路径或抛出 `ScriptFailedError`。

### SMS 异步 Post-Processing

日报（`daily`）执行流程中，`query_sms_abnormal.py` 在后台线程运行，与主流程（query → kpi → export）并发。SMS 数据写入 `sms_abnormal.json`，`daily_kpi.py` 在 KPI 计算时读取并合并到最终报告中。SMS 查询失败不会阻塞主报告生成。

### 组织树透传

为避免重复查询，前端表单将设备元数据（`equipment_type`、`equipment_ids`、`equipment_labels`、`equipment_meta`）通过 `report_direct_execute` 工具透传到脚本。`query_daily.py` 通过 `--equipment-meta` 参数接收，跳过内部组织树查询。

### 性能埋点

七段计时（表单交互、组织树查询、当天 InS、对比日 InS、SMS、KPI 计算、导出）输出到 `<output_dir>/.perf/<trace_id>.jsonl`。通过 `PerfTracer` 类（`_perf.py`）控制，`REPORT_RUN_ID` 环境变量提供 trace_id。

### 错误处理

`DirectExecutionError` 层级:
- `SCRIPT_FAILED` - 脚本执行失败
- `NO_DATA` - 无数据
- `INTERNAL_ERROR` - 内部错误

### SOUL.md 简化

直接执行 Agent 的 SOUL.md 不再包含 DSL 状态机约束；深链参数直接触发 `report_direct_execute`。

## 遥测 (Phase 7)

**模块**: `report_templates/telemetry.py`

线程安全的内存收集器，镜像 `RenderUIMetrics` 模式 —— 无 Prometheus / OTel 依赖。

### 事件类型

| 事件 | 触发点 |
|------|--------|
| `report_run_outcome` | state.transition → terminal |
| `fallback_triggered` | `report_template_record_fallback` 工具 |
| `validator_outcome` | validator.validate_dsl |
| `storage_snapshot` + `version_count_snapshot` | storage_scanner |
| `skill_unavailable` | data_runner + script_registry |

### 存储

- 内存计数 + 追加到 `{DEER_FLOW_HOME}/report-templates/.telemetry.log` (JSONL)
- 禁用 JSONL sink: `DEER_FLOW_REPORT_TELEMETRY_LOG=0`

### HTTP 接口

- `GET /api/telemetry/report-templates/summary` - 实时计数器快照
- `POST /api/telemetry/report-templates/scan-storage` - 触发存储扫描
- `POST /api/telemetry/report-templates/scan-versions` - 触发版本扫描
