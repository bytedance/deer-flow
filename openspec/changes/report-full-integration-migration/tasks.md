# Report Full Integration Migration - Implementation Tasks

**当前仓库基线**:
- `_ins_provider.py` 聚合函数仍存活，sync wrapper 可用
- `_platform_bridge.py` 的 `_transform_canonical_to_script_shape` 返回全空占位（KPI 全 None）
- `query_daily/weekly/monthly.py` 已有 `is_platform_mode()` 分支和 `_fetch_*_via_platform()` 框架
- `integrations/cli.py` action 模式已完成（`aggregate_kpi` / `select_points`）
- `kpi_aggregator.py` 已完成（6 种推导方法的纯函数）
- 5 个 builtin 模板 DSL **无** `provider: platform` 声明
- `DataStep` schema **无** `provider` 字段
- `data_runner.py` **不**注入 `USE_PLATFORM`

## 1. Schema + data_runner 布线

- [x] 1.1 `schema.py` `DataStep` 新增 `provider: str | None = None` 字段，`extra="forbid"` 保持不变
- [x] 1.2 `schema.py` `DataStep` 添加 `@field_validator("provider")` 校验值在 `{"platform", "ins", "demo", "http", None}` 中
- [x] 1.3 `data_runner.py` `run_script()` 签名新增 `provider: str | None = None` 参数
- [x] 1.4 `run_script()` 根据 `provider` 值向 subprocess env 注入环境变量：`"platform"` → `USE_PLATFORM=true`，`"ins"|"demo"|"http"` → `USE_PROVIDER=<value>`
- [x] 1.5 `run_data_steps_and_transforms()` 从 `step.get("provider")` 提取并传递给 `run_script()`
- [x] 1.6 更新 `test_data_runner_provider.py` 使现有测试通过（或重写以匹配新接口）

## 2. 模板 DSL 声明 provider

- [ ] 2.1 `daily-equipment/default.yaml` 的 `data_steps[0]` 加 `provider: platform`
- [ ] 2.2 `weekly-equipment/default.yaml` 的 `data_steps[0]` 加 `provider: platform`
- [ ] 2.3 `monthly-equipment/default.yaml` 的 `data_steps[0]` 加 `provider: platform`
- [ ] 2.4 `trend-equipment/default.yaml` 的 `data_steps[0]` 加 `provider: platform`
- [ ] 2.5 `diagnosis-fault/default.yaml` 的 `data_steps` 加 `provider: platform`
- [ ] 2.6 运行 `test_builtin_report_templates.py` 确认所有模板通过校验

## 3. 脚本清理 — 移除旧直连路径

- [ ] 3.1 `_ins_provider.py` 聚合函数体替换为 `raise NotImplementedError`
- [ ] 3.2 `_data_provider_impls.py` 移除 `InsDailyProvider` / `InsWeeklyProvider` / `InsMonthlyProvider` 的注册调用
- [ ] 3.3 `_data_providers.py` 将 `daily` / `weekly` / `monthly` 从 `INS_ONLY_SOURCES` 改为只支持 `"platform"` 模式
- [ ] 3.4 `_data_providers.py` 新增或改造 provider 注册：`register_provider("daily", "platform", PlatformDailyProvider)` 等三个
- [ ] 3.5 `_data_provider_impls.py` 新增 `PlatformDailyProvider` / `PlatformWeeklyProvider` / `PlatformMonthlyProvider`，内部调用 `_platform_bridge.call_capability` + `call_action`

## 4. Platform bridge 数据转换修复

- [ ] 4.1 修复 `_fetch_day_via_platform()` 的 `_transform_canonical_to_script_shape()` 替换，返回真实 KPI 数据
- [ ] 4.2 修复 `_fetch_week_via_platform()` 和 `_fetch_month_via_platform()` 同理
- [ ] 4.3 确认 `call_action("aggregate_kpi", ...)` 返回的 KPI dict 正确映射到脚本需要的 key 名（runtime_rate 而非 runtimeRate 等）
- [ ] 4.4 `_platform_bridge.py` 超时时间调整为 300 秒（月报需要更长窗口）

## 5. Agent SOUL.md 简化

- [ ] 5.1 `ai-report--daily/SOUL.md` 移除 fallback 全部内容（双轨决策、fallback 触发场景、Round 1/1.5/2 表单 JSON、`query_daily.py` shell 命令、`report_template_record_fallback` 调用、"正在使用兼容模式"提示）
- [ ] 5.2 `ai-report--weekly/SOUL.md` 同上
- [ ] 5.3 `ai-report--monthly/SOUL.md` 同上
- [ ] 5.4 三个 SOUL.md 替换"启动决策"章节为简化的 DSL-only 指令：调用 `report_template_get`，命中直接执行，不命中报告错误
- [ ] 5.5 确认 Deep-Link 参数直达逻辑保留（不影响 fallback 移除）

## 6. 验证

- [ ] 6.1 `make test` 全量后端测试，确认无回归
- [ ] 6.2 `test_builtin_report_templates.py` 全量通过
- [ ] 6.3 `test_data_runner_provider.py` 通过（provider env 注入行为）
- [ ] 6.4 `test_report_platform_bridge.py` 通过（platform bridge）
- [ ] 6.5 `test_ai_report_daily_pipeline.py` 通过（日报管线）
- [ ] 6.6 `test_ai_report_weekly_pipeline.py` 通过（周报管线）
- [ ] 6.7 `test_ai_report_monthly_pipeline.py` 通过（月报管线）
- [ ] 6.8 真实 InS 环境 E2E 烟雾测试：`daily-equipment` 模板生成完整报告，KPI 非空
- [ ] 6.9 真实 InS 环境 E2E 烟雾测试：`weekly-equipment` / `monthly-equipment` 模板生成完整报告
