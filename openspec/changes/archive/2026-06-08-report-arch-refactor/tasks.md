# Report Architecture Refactor - Implementation Tasks

## 1. 直执行器模块搭建

- [x] 1.1 创建 `backend/packages/harness/deerflow/report_executor/` 模块目录，包含 `__init__.py`、`executor.py`、`errors.py`
- [x] 1.2 实现 `errors.py`：定义 `DirectExecutionError`、`ScriptFailedError`、`NoDataError` 异常类，支持结构化错误码（`SCRIPT_FAILED`、`NO_DATA`）
- [x] 1.3 编写 `executor.py` 骨架：`DirectReportExecutor` 类，接受 `report_type`、`scope`、`equipment_type`、`compare_with`、`equipment_ids`、`equipment_labels`、`kpi_keys` 参数
- [x] 1.4 实现日报直执行流程：编排 `query_daily.py` → `daily_kpi.py` → `export_report.py` 三步脚本调用，使用 subprocess 执行并解析 stdout JSON
- [x] 1.5 实现周报直执行流程：编排 `query_weekly.py` → `weekly_kpi.py` → `export_report.py`，复用日报的错误处理和产物管理逻辑
- [x] 1.6 实现月报直执行流程：编排 `query_monthly.py` → `monthly_kpi.py` → `export_report.py`
- [x] 1.7 实现参数默认值逻辑：`equipment_ids=None` 时传 `--scope all`，`kpi_keys=None` 时使用模板默认 KPI 集合
- [x] 1.8 实现产物输出：所有报告写入 `/mnt/user-data/outputs/`，返回 `{report_run_id, artifacts: [{path, type}], status}`

## 2. 直执行工具注册

- [x] 2.1 在 `backend/packages/harness/deerflow/tools/builtins/` 创建 `report_direct_tools.py`，实现 `report_direct_execute` LangChain tool
- [x] 2.2 工具内部调用 `DirectReportExecutor.execute()`，捕获异常并返回结构化错误 JSON（`{error: {code, message, step}, status: "failed"}`）
- [x] 2.3 工具成功时返回 `{report_run_id, artifacts, status: "success"}`，并通过 `present_files` 暴露 `.md` / `.pdf` 产物
- [x] 2.4 在 `tools/tools.py` 的 `get_available_tools()` 中注册 `report_direct_execute`，但仅在 agent name 匹配 builtin 三报时绑定

## 3. 执行器路由中间件

- [x] 3.1 创建 `backend/packages/harness/deerflow/agents/middlewares/report_executor_router.py`
- [x] 3.2 实现路由逻辑：检查 `agent_config.name`，匹配 `ai-report--daily` / `ai-report--weekly` / `ai-report--monthly` 时标记为 direct，其他标记为 dsl
- [x] 3.3 Builtin agent 绑定 `report_direct_execute`，移除 `report_template_*` 工具绑定
- [x] 3.4 Custom agent 绑定 `report_template_*` 工具，移除 `report_direct_execute` 绑定
- [x] 3.5 在 `build_lead_runtime_middlewares()` 中注册 `ReportExecutorRouter`，位于工具绑定阶段之后

## 4. SOUL.md 简化

- [x] 4.1 简化 `agents/builtin/ai-report--daily/SOUL.md`：移除 deep-link 直达约束（~30 行），替换为"参数齐全时调用 `report_direct_execute`"（~5 行）
- [x] 4.2 简化 `agents/builtin/ai-report--weekly/SOUL.md`：同上
- [x] 4.3 简化 `agents/builtin/ai-report--monthly/SOUL.md`：同上
- [x] 4.4 更新 `PassthroughParamsMiddleware`：根据 agent name 注入不同的 deep-link 执行指令（direct vs DSL）

## 5. Blueprint fork 机制

- [x] 5.1 在 Blueprint YAML schema 中新增 `executor_type` 字段（`"direct"` | `"dsl"`），默认 builtin blueprint 为 `"direct"`
- [x] 5.2 修改 Fork API（`POST /api/report-templates/{id}/fork`）：fork builtin blueprint 时自动将 `executor_type` 改为 `"dsl"`
- [x] 5.3 Fork 后的模板自动关联 `ai-report--custom` agent
- [x] 5.4 更新 Blueprint 生成脚本：从 builtin YAML 生成 blueprint 时设置 `executor_type: "direct"`

## 6. 测试

- [x] 6.1 编写 `tests/test_report_direct_executor.py`：覆盖 daily/weekly/monthly 三种类型的直执行流程，验证脚本调用顺序和参数传递
- [x] 6.2 编写 `tests/test_report_direct_execute_tool.py`：验证工具的错误处理（`SCRIPT_FAILED`、`NO_DATA`）和成功返回格式
- [x] 6.3 编写 `tests/test_report_executor_router.py`：验证路由逻辑（builtin agent → direct，custom agent → dsl）和工具绑定
- [x] 6.4 更新 `tests/test_ai_report_deeplink_soul.py`：验证简化后的 SOUL.md 包含 `report_direct_execute` 指令，不再包含 DSL 状态机约束
- [x] 6.5 编写 `tests/test_blueprint_executor_type.py`：验证 fork builtin blueprint 时 `executor_type` 自动转为 `"dsl"`
- [x] 6.6 运行全量测试：`make test`，确保无回归

## 7. 文档更新

- [x] 7.1 更新 `backend/CLAUDE.md`：在 Report Template Platform 章节增加直执行器说明（模块路径、工具名、路由规则）
- [x] 7.2 更新 `docs/plans/` 中的相关设计文档：标注 builtin 三报已迁移到直执行架构
- [x] 7.3 更新 API 文档：说明 `report_direct_execute` 工具参数和返回值
