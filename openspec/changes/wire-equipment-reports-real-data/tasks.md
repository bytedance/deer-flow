## 0. Pre-work: 抓样 + 扩展 features-tool

- [~] 0.1 在 docker sandbox 内（或运维侧）用现有 `INS_USERNAME` / `INS_PASSWORD` 调用 `getComponentByMachineIds`，对 2k / 6k / 8k / 9k 各序列至少抓 1 条机器节点的真实 JSON 样本（**已有 2k / 9k / 6k 样本**：2k=P-3101A 进料泵 / 9k=C1601 循环气压缩机 / 6k=P-203A 出口_TH 腐蚀监测探头），补抓 8k 样本，保存到 `docker/sandbox/features-tool/tests/fixtures/components_{2k,6k,8k,9k}.json`（gitignored 或脱敏后入库）  *(ops 任务：需要在线 InS 访问；代码已不依赖 8k 真实样本，单元测试用合成 fixtures 走通即可)*
- [x] 0.2 [Open Question O1] **已通过 InS 服务端 `MachineType` Java 枚举确认权威值**：`type=1`(MAC)→8K、`type=4`(PUMP)→2K、`type=6`(PIPELINE)→6K、`type=9`(RC)→9K（其它含 `type=16`(VALVE)→7K 与 PUMP 走 5K 等本提案不接入的情况，走 8K 兜底）。把决议写回 `design.md` 的 D10 段
- [x] 0.3 扩展 `docker/sandbox/features-tool/ins/client.py:slim_component(...)`：对每个**测点节点**（不是机器节点）提取 `endpoint_series`（值域 `"2k"|"6k"|"8k"|"9k"`），按以下优先级解析（positionType 范围与成员名来自 InS 服务端 `PointPositionType` Java 枚举，权威）：
   - 测点 `positionType in {22..30}` → `"2k"`（22=STA W203过程量、23=VIB W203振动（实测 P-3101A "泵前轴承_A"）、24=OTHER_VIB、25=STA_GENERAL、26=M_VIB、27=S_VIB、28=STA_W205、29=REV_SPEED、30=MAGNETIC_FLUX）
   - 测点 `positionType in {61..64}` → `"6k"`（61=STA、62=TH（实测 P-203A 出口_TH）、63=P 腐蚀探针、64=OTHER_TH 离线检测）
   - 测点 `positionType in {81..83}` → `"8k"`（81=KEY 键相、82=STA 过程量、83=VIB 振动）；**保留现有 8k STA(82) 子类型识别**：posName 含"轴承" → bearing_temp、含"阀" → valve_temp、含"流量" → flow_rate、含"出口压力" → outlet_pressure
   - 测点 `positionType in {91..99}` → `"9k"`（91=JSZD、92=SZT、93=PBX、94=PBY、95=GTZD、96=GCYL、97=KEY、98=STA 子类型遇到再加入、99=ZCYL）
   - 否则回退到机器层 `type` 映射（`type=4` PUMP → `"2k"`、`type=6` PIPELINE → `"6k"`、`type=9` RC → `"9k"`、`type=1` MAC → `"8k"`）
   - 仍未识别 → `"8k"`（兜底，与现有 7 个生产 skill 行为一致）
   - **2k 测点额外透传 B/C/D 三级阈值**：`alarm_thresholds: {<feature>: {B, C, D}}`，feature 取值 `v_rms`/`a_peak`/`a_rms`/`kurtosis`/`margin`/`pulse`/`wave`（从测点对象上的 `vRmsBValue/CValue/DValue`、`gBValue/CValue/DValue`、`aPeakBValue/CValue/DValue`、`kurtosisBValue/CValue/DValue`、`marginBValue/CValue`、`pulseBValue/CValue/DValue`、`waveBValue/CValue/DValue` 字段映射，缺失字段不写入）；以及 `index`（legend 数组原样透传）
- [x] 0.4 在 `client.py` 新增模块级辅助 `parse_trend_response(rows, series)` + 常量 `_TWO_K_NAME_KEY_MAP`：
   - `series in {"8k","9k"}` → 直返 rows
   - `series == "6k"` → 把每行的 `value` 数组用内部 `key` 字段展平为 `{datatime, corrosionRate, thinningRate, thickness, temperature, ...}`；字符串值 `try float(...)`，失败 / 空字符串 → `None`
   - `series == "2k"` → 把每行的 `value` 数组用内部中文 `name` 字段经 `_TWO_K_NAME_KEY_MAP` 翻译为 ASCII key 后展平：`"速度有效值" → v_rms`、`"加速度峰值" → a_peak`、`"加速度有效值" → a_rms`、`"位移峰峰值" → pp_value`、`"包络谱峰值" → envelope_peak`、`"峭度" → kurtosis`、`"裕度" → margin`、`"脉冲指标" → pulse`、`"波形指标" → wave`；未知 `name` 原样作 key + debug log（便于补样本时直接发现）
   - 所有内部 `value` 走 `try/except float(...)`；非数字 / 空字符串 → `None`，上层聚合时跳过
   - 非 list 的 `value` 字段 → 跳过整行（debug log）
- [x] 0.5 扩展 `InsApiClient.get_trend_data(...)`：新增 kwargs `endpoint_series: str | None = "8k"`、`factory_id: str | None = None`、`density: str|int = 1`、`include_filter: str | None = None`、`type_list: str | None = None`；按 `_ENDPOINT_PATH_BY_SERIES` 路由；`factory_id is None` 时**不附加** `factoryId` 参数；9k 自动注入 `density=high` / `includeFilter=history` / `typeList=<features>`；调用 `parse_trend_response(rows, series)` 后再返回
- [x] 0.6 在 `docker/sandbox/features-tool/tests/test_ins_client.py` 新增 case：
   - 4 路径路由 case：每个 mock `_get_json` 验证 path、`gpids`、`density`、9k 的 `includeFilter` / `typeList` 拼装正确
   - `factory_id=None` → 请求 URL 不含 `factoryId` 参数
   - `factory_id="xxx"` → 请求 URL 含 `factoryId=xxx`
   - **2k 嵌套响应** → `parse_trend_response` 经 `_TWO_K_NAME_KEY_MAP` 后 `v_rms`/`a_peak` 字段正确，未知 name `"未知指标"` 原样作 key（不抛异常）
   - **6k 嵌套响应** → `parse_trend_response` 展平后 `corrosionRate`/`thinningRate`/`thickness`/`temperature` 字段正确，空字符串 → `None`，字符串 → float
   - 8k 扁平响应 → `parse_trend_response` 直返不变
   - 9k 扁平响应 → `parse_trend_response` 直返不变
   - `slim_component` 对 `positionType=23` 的 2k 测点产出 `endpoint_series="2k"` + `alarm_thresholds: {v_rms: {B, C, D}, a_peak: {B, C, D}, kurtosis: {B, C, D}, ...}`
- [~] 0.7 重建镜像：`docker build -f docker/sandbox/Dockerfile -t deer-flow-sandbox-features-tool:latest docker/sandbox`；推内网 registry（如有）；本地 `make docker-start` 验证

## 0.5 Tool wrappers: features-tool/tools/{2k,6k,9k} 三件套（共 9 个 wrapper 脚本）

> 依赖 §0.3–0.5 已完成的 client.py 4 路径路由 / `endpoint_series` / `parse_trend_response`。每个 wrapper 仅为现有 8K 默认 tool 的薄派生：复制模板 → 强制 `endpoint_series=<series>` → 按 series 调整默认 feature 列表与 CLI 帮助文案。输入输出 schema 与 8K 版保持一致，下游 skill 的 `run.sh` 只切换调用脚本名即可。

- [x] 0.8 派生 **2K 系列** 三件套：`docker/sandbox/features-tool/tools/get_trend_data_2k_tool.py` / `extract_trend_features_2k_tool.py` / `device_analysis_2k_tool.py`
   - 复制 8K 默认模板（`get_trend_data_tool.py` / `extract_trend_features_tool.py` / `device_analysis.py`），在 `InsApiClient.get_trend_data(...)` 调用处显式传 `endpoint_series="2k"`；`device_analysis_2k_tool.py` 在 `slim_component(...)` 返回后按 `endpoint_series == "2k"` 过滤测点节点
   - 输出 JSON 在 8K 模板基础上保留新增的 `alarm_thresholds` 字段（B/C/D 三级阈值，2K 测点专属）
   - CLI 帮助文案与 usage 字符串提示 "2K（机泵 PUMP，positionType 22..30）"
- [x] 0.9 派生 **6K 系列** 三件套：`get_trend_data_6k_tool.py` / `extract_trend_features_6k_tool.py` / `device_analysis_6k_tool.py`
   - 强制 `endpoint_series="6k"`；CLI 未指定 feature 时默认列表为 `["corrosionRate", "thinningRate", "thickness", "temperature"]`（CLI 显式传值仍可覆盖）
   - 6K 嵌套响应的展平已经在 client.py `parse_trend_response(rows, "6k")` 内部完成，wrapper 不需要二次解析
   - CLI 帮助文案提示 "6K（静设备腐蚀监测 PIPELINE，positionType 61..64）"
- [x] 0.10 派生 **9K 系列** 三件套：`get_trend_data_9k_tool.py` / `extract_trend_features_9k_tool.py` / `device_analysis_9k_tool.py`
   - 强制 `endpoint_series="9k"`；**不在** wrapper 层手工拼 `density=high` / `includeFilter=history` / `typeList=<features>`，由 client.py 内部按 `endpoint_series=="9k"` 自动注入（保持 wrapper 与 8K 模板形态一致，避免参数膨胀）
   - CLI 帮助文案提示 "9K（往复 / 高端旋转机组 RC，positionType 91..99）"
- [x] 0.11 在 `docker/sandbox/features-tool/tests/test_tools.py`（如不存在则新建，与 §0.6 的 `test_ins_client.py` 同级）增加 9 个 wrapper 的 smoke 测试：
   - 每个 `get_trend_data_*k_tool.py` mock `InsApiClient.get_trend_data`，断言入参 `endpoint_series` 透传为 `"2k"` / `"6k"` / `"9k"`
   - 每个 `device_analysis_*k_tool.py` 喂入混合 series 的 component tree（同时含 2K/6K/8K/9K 测点），断言输出只含目标 series 的测点
   - 每个 `extract_trend_features_*k_tool.py` 验证调用链上 `get_trend_data` 的 `endpoint_series` 参数正确

## 1. Adapter module: _ins_provider.py

- [x] 1.1 Create `skills/custom/data-analyst/scripts/_ins_provider.py` with module-level `sys.path` injection of `os.environ.get("FEATURES_TOOL_ROOT", "/opt/features-tool")` and a try/except `from ins import InsApiClient, load_ins_settings` that sets `_FEATURES_TOOL_AVAILABLE` boolean
- [x] 1.2 Read optional env `INS_FACTORY_ID` at module level; if set, every `get_trend_data` call passes `factory_id=<env-value>`; otherwise `factory_id=None`
- [x] 1.3 Define `_KPI_FEATURE_MAP` constant covering THREE families: (a) **2k multi-feature vibration** KPIs (`vibration_velocity_rms` ← `v_rms`, `vibration_acceleration_peak` ← `a_peak`, `kurtosis_index` ← `kurtosis`, etc. — sourced from `positionType in {20..29}` points); (b) **rotating** KPIs (`vibration_level` ← 8k `pp_value`, `bearing_temp`, `valve_temp`, `flow_rate`, `outlet_pressure`, `runtime_rate`, `alarm_count`, `downtime_count` — sourced from 8k / 9k `positionType in {80..89}` points); (c) **static-equipment corrosion** KPIs (`corrosion_rate`, `thickness_loss`, `thinning_rate`, `process_temperature` — sourced from 6k `positionType=62` points). Each entry specifies `{positionType_filter, feature, name_keywords?, derivation, expected_series, alarm_tier?}` where `alarm_tier` selects C-level (`alarm`) or D-level (`danger`) threshold for 2k KPIs
- [x] 1.4 Implement `_select_points_for_kpi(components, kpi_key)` — walks the slim component tree, filters by `positionType` + name keywords, returns each matching point's `(point_id, endpoint_series, h_alarm, hh_alarm, alarm_thresholds)` tuple (where `alarm_thresholds` is the 2k `{<feature>: {B, C, D}}` dict, possibly empty for 8k/6k) — used for both routing and `alarm_count` derivation
- [x] 1.5 Implement `_aggregate_trend_to_kpi(rows, kpi_key, point_meta)` — daily mean (skipping `None` from 2k/6k empty-string conversion), hourly bucket means (24 floats), `runtime_rate = count(speed>0)/count(*)`, `alarm_count` derivation:
   - For 8k KPIs: `sum(value > h_alarm)`
   - For 2k KPIs: select the configured tier (default C) from `point_meta.alarm_thresholds[<feature>][<tier>]`, then `sum(value > threshold)`; if `D` tier requested, separately compute `danger_count`
   - `downtime_count = falling-edge count of speed`
   - `thickness_loss = first_thickness - last_thickness`
- [x] 1.6 Implement async `_async_fetch_payload(date_or_period, equipment_ids, kpi_keys, eq_type, compare_period_or_None, equipment_meta)` — orchestrates `get_components` (cached per machine) + bucket points by `endpoint_series` + issue **one `get_trend_data` call per (component_id, endpoint_series) bucket** + aggregation; returns the dict shape that matches the `current` / `compare` blocks of `daily_data.json` / `weekly_data.json` / `monthly_data.json`
- [x] 1.7 Implement sync wrappers `fetch_daily_payload(...)`, `fetch_weekly_payload(...)`, `fetch_monthly_payload(...)` using `asyncio.run(_async_...)` and converting any `httpx.HTTPError` / `RuntimeError` / unmappable-KPI failure into `HttpProviderError("...")`
- [x] 1.8 Add a small unit test (`backend/tests/test_ins_provider_unit.py`) that mocks `InsApiClient.get_components` + `get_trend_data` and asserts:
   - mappable 2k KPIs aggregate to expected values (2k path, after `_TWO_K_NAME_KEY_MAP` flattening)
   - mappable rotating 8k KPIs aggregate to expected values (8k path)
   - mappable corrosion KPIs aggregate to expected values (6k path, with `None` skipped from empty strings)
   - mixed 2k + 6k + 8k KPI list on the same machine issues 3 separate `get_trend_data` calls (one per endpoint_series bucket)
   - 2k `alarm_count` for `vibration_velocity_rms` counts samples > `vRmsCValue` (C-tier default); when KPI configured with `alarm_tier=D`, threshold becomes `vRmsDValue`
   - unmappable KPI raises `HttpProviderError` with key name
   - `_FEATURES_TOOL_AVAILABLE=False` raises `HttpProviderError("features-tool not available...")`
   - `INS_FACTORY_ID` env set → `factory_id=<value>` is passed through to `get_trend_data`

## 2. Provider registration (_data_providers.py + _data_provider_impls.py)

- [x] 2.1 Add three new keys (`daily`, `weekly`, `monthly`) to `_PROVIDER_FACTORIES` in `_data_providers.py`
- [x] 2.2 Define three `Protocol` classes (`DailyDataProvider`, `WeeklyDataProvider`, `MonthlyDataProvider`) declaring the `fetch(...)` signature each script needs
- [x] 2.3 Implement `DemoDailyProvider` in `_data_provider_impls.py`: lazy-load `query_daily` and call its existing `_demo_day` helper; return `ProviderResult(data=..., data_source=DEMO_FALLBACK)`
- [x] 2.4 Implement `InsDailyProvider`: import `_ins_provider.fetch_daily_payload`; on success return `ProviderResult(data=..., data_source="ins")`; on exception re-raise as `HttpProviderError`
- [x] 2.5 Implement `DemoWeeklyProvider` and `InsWeeklyProvider` analogously
- [x] 2.6 Implement `DemoMonthlyProvider` and `InsMonthlyProvider` analogously
- [x] 2.7 Register all six providers via `register_provider("daily"|"weekly"|"monthly", "demo"|"ins", <class>)` at module import
- [x] 2.8 Update `get_provider` resolution to accept `mode="ins"` (currently the registry already honors arbitrary mode names — verify no hard-coded "http" anywhere blocks it)

## 3. Wire query scripts to fetch_with_fallback

- [x] 3.1 In `query_daily.py`: import `fetch_with_fallback`; rewrite `fetch_day(...)` to call `fetch_with_fallback(source="daily", fetch_args={...})`; preserve `_demo_day` as the demo provider's backing function (no signature change to `_demo_day`)
- [x] 3.2 In `query_daily.py:build_result`: capture `ProviderResult.data_source` and `notes` from each `fetch_day` call; if `current` and `compare` data_sources disagree, downgrade the entire payload to `demo_fallback` (re-call demo for both blocks) and append a note
- [x] 3.3 Add `data_source` and `data_notes` as top-level fields in `build_result`'s returned dict; ensure `write_payload` serializes them
- [x] 3.4 Repeat 3.1–3.3 for `query_weekly.py:fetch_week` / `build_result`
- [x] 3.5 Repeat 3.1–3.3 for `query_monthly.py:fetch_month` / `build_result`

## 4. KPI transforms preserve the new fields

- [x] 4.1 Edit `daily_kpi.py:compute` to copy `data_source` and `data_notes` from input payload to output `result` dict
- [x] 4.2 Edit `weekly_kpi.py:compute` analogously
- [x] 4.3 Edit `monthly_kpi.py:compute` analogously
- [x] 4.4 Add a derived `data_source_banner` string field to each `*_kpi.py:compute` output (constructed per the banner format) so DSL templates can pin it via JSONPath

## 5. Markdown banner in export_report.py

- [x] 5.1 In `skills/custom/data-analyst/scripts/export_report.py:render_markdown`, prepend a banner line based on `payload.get("data_source")` and `payload.get("data_notes")`, matching exact strings in spec Requirement "Markdown banner reflecting data source"
- [x] 5.2 Make banner injection idempotent by detecting if the existing first line already starts with `> ✅ ` or `> ⚠️ `
- [x] 5.3 Confirm `write_report(payload, "md")` and `write_report(payload, "pdf")` both inherit the banner (PDF goes through markdown internally — should be automatic)

## 6. SOUL prompts (硬编码 fallback path)

- [x] 6.1 In `agents/builtin/ai-report--daily/SOUL.md` "Round 2 回调：生成日报" 步骤 6 加入约束："读取 `daily_kpi.json` 的 `data_source` 字段后，必须保留 `render_markdown` 已渲染好的首行横幅，不得删改、不得移动"
- [x] 6.2 In "核心原则" 段加入 "数据来源标识必须出现在所有日报正文首行；如发现 markdown 首行非 `>` 起始的横幅，立即调用 `render_ui` 重新渲染"
- [x] 6.3 Repeat for `agents/builtin/ai-report--weekly/SOUL.md`
- [x] 6.4 Repeat for `agents/builtin/ai-report--monthly/SOUL.md`

## 7. Builtin DSL templates (DSL primary path)

- [x] 7.1 In `agents/builtin/report-templates/daily-equipment/default.yaml`, prepend a new `markdown` section (id `data_source_banner`) to `sections:`, with `source: $.steps.daily_kpi.daily_kpi.data_source_banner`
- [x] 7.2 Repeat 7.1 for `weekly-equipment/default.yaml` (source pointing at `weekly_kpi.weekly_kpi.data_source_banner`)
- [x] 7.3 Repeat 7.1 for `monthly-equipment/default.yaml` (source pointing at `monthly_kpi.monthly_kpi.data_source_banner`)
- [x] 7.4 Run `pytest backend/tests/test_builtin_report_templates.py` and confirm validator regressions are zero

## 8. Tests

- [x] 8.1 Create `backend/tests/test_ai_report_daily_ins_provider.py` covering: demo default; InS success — 2k only (mock `get_trend_data` with 2k nested response containing `速度有效值`/`加速度峰值`, verify name-to-key flattening); InS success — rotating 8k only (8k flat response); InS success — corrosion 6k only (6k nested response); InS success — mixed 2k + 6k + 8k on the same machine (verify 3 separate `get_trend_data` calls with different `endpoint_series` values); features-tool unavailable → fallback; InS network failure → fallback; unmappable KPI → fallback; 2k `alarm_count` derivation against `vRmsCValue` (C-tier); `data_source` / `data_notes` propagation to `daily_data.json` and `daily_kpi.json`
- [x] 8.2 Create `backend/tests/test_ai_report_weekly_ins_provider.py` with the same scenarios
- [x] 8.3 Create `backend/tests/test_ai_report_monthly_ins_provider.py` with the same scenarios
- [x] 8.4 Add a parametrized banner-rendering test to each new test file: assert `render_markdown` first line for `data_source=demo_fallback (no notes)`, `demo_fallback (with notes)`, `ins`, and the idempotent re-render case
- [x] 8.5 Update `test_ai_report_daily_query.py` / `test_ai_report_weekly_query.py` / `test_ai_report_monthly_query.py` to additionally assert `data_source == "demo_fallback"` and `data_notes == []` in default invocations (additive change, no deletions)
- [ ] 8.6 Run `make test` from `backend/` and confirm zero regressions

## 9. Documentation

- [x] 9.1 Add a "设备日/周/月报真数据（InS）" subsection to `backend/docs/HTTP_CONNECTORS.md` documenting:
  - `DEER_FLOW_DATA_PROVIDER=ins` as the only required env to enable real data
  - `INS_FACTORY_ID` as an optional override (default unset)
  - The 4 endpoint series (2k 旧版多 feature 振动 / 6k 静设备腐蚀监测 / 8k 旋转机组默认 / 9k 高端旋转机组) with their use cases and response shape differences (2k/6k nested vs 8k/9k flat)
  - The 2k name-to-key normalization map (`_TWO_K_NAME_KEY_MAP`) and the B/C/D threshold tier semantics
  - Fallback triggers (network / 401 / KPI mapping / device not found / features-tool unavailable)
  - The docker-sandbox-only constraint
- [x] 9.2 Update `backend/CLAUDE.md` "Skills System" / "Data analyst" area to mention `data_source` / `data_notes` fields, the 4 endpoint series, and link to the new docs subsection
- [x] 9.3 If frontend markdown component does not render `>` blockquotes correctly, file a follow-up; else no-op

## 10. Manual validation

- [ ] 10.1 Local docker dev: `make docker-start`; generate a daily report through the UI without setting `DEER_FLOW_DATA_PROVIDER`; verify markdown shows the demo banner with reason "未配置真实数据源"
- [ ] 10.2 Local docker dev with `DEER_FLOW_DATA_PROVIDER=ins` injected into `sandbox.environment`: generate a daily report for a known InS rotating 8k/9k device ID (e.g. 9k 压缩机 C1601 `id=230520011328851`); verify the report shows the InS real-data banner and that KPI values change with date (no longer hash-deterministic)
- [ ] 10.3 Generate a daily report for a known **2k** multi-feature vibration device (e.g. P-3101A 进料泵 `id=260325070149111`, with `positionType=23` points like "泵前轴承_A"); verify `vibration_velocity_rms` (`v_rms`) / `vibration_acceleration_peak` (`a_peak`) come from real 2k data (not demo hash) and 2k `alarm_count` is computed against `vRmsCValue`
- [ ] 10.4 Generate a daily report for a known 6k corrosion-monitored equipment (e.g. P-203A 出口_TH 探头); verify `corrosion_rate` / `thickness_loss` come from real data (not demo hash)
- [ ] 10.5 Generate a daily report for a machine that has both 2k vibration points and 6k corrosion points (or 8k + 6k mixed bucket); verify both KPI families are real and `_ins_provider` issued **2-3 separate** endpoint calls per `endpoint_series` bucket (observable via debug log)
- [ ] 10.6 Inject a deliberately bogus device ID; verify report falls back to demo with banner reason quoting "device <id> not found in InS"
- [ ] 10.7 Repeat 10.1–10.6 for weekly and monthly reports
- [ ] 10.8 Verify PDF export inherits the banner (open `daily_report.pdf` and check first line)
- [ ] 10.9 Verify telemetry: in `backend/.deer-flow/report-templates/.telemetry.log`, observe that fallback events are recorded (existing `report_template_record_fallback` instrumentation should pick this up automatically)

## 11. New skills: 10 个 skill 目录（9 个 InS 多 series 数据获取层 + 1 个 6K 静设备腐蚀诊断上层）

> **依赖**：§0（client.py 4 路径路由 / `endpoint_series` / `slim_component` 字段透出）+ §0.5（9 个 tool wrapper 脚本）。
> **与主链路并行**：本段与 §1–§9（data-analyst provider 链路）相互独立，可并行实施；只有 §8.1 的 skill 单元测试需要本段 SKILL.md + wrapper 都到位。
> **统一形态**：每个 skill 目录复制现有 8K 模板（`ins-get-trend-data` / `ins-extract-trend-features` / `ins-device-analysis` / `pump-fault-diagnosis`）→ 改名 → 改 `run.sh` 调用 §0.5 派生的 `*_<series>_tool.py` → 在 SKILL.md 的 "When to Use This Skill" / "Default Feature Mapping" / "Notes" 段落加 series 特异说明。除 SKILL.md + run.sh 外不写新 Python 代码。

### 11.1 2K 系列三件套（机泵 PUMP，positionType 22..30）

- [x] 11.1.1 创建 `skills/custom/ins-get-trend-data-2k/`：`SKILL.md`（基于 `ins-get-trend-data/SKILL.md` 模板）+ `scripts/run.sh`（调 `tools/get_trend_data_2k_tool.py`）。SKILL.md 的 "Default Feature Mapping" 段改为 2K 默认特征：`positionType=23` 振动点 → `["v_rms", "a_peak", "a_rms", "kurtosis", "margin", "pulse", "wave"]`（经 client.py 内 `_TWO_K_NAME_KEY_MAP` 翻译后的 ASCII key），`positionType=22` 过程量 → `["value"]`，`positionType=29` 转速 → `["speed"]`
- [x] 11.1.2 创建 `skills/custom/ins-extract-trend-features-2k/`：模板派生自 `ins-extract-trend-features/`，`run.sh` 调 `extract_trend_features_2k_tool.py`；SKILL.md 描述 2K 多 feature 振动测点的特征提取语义
- [x] 11.1.3 创建 `skills/custom/ins-device-analysis-2k/`：模板派生自 `ins-device-analysis/`，`run.sh` 调 `device_analysis_2k_tool.py`；SKILL.md 在 "Output" 段增加 `alarm_thresholds: {<feature>: {B, C, D}}` 字段说明，提示下游诊断 skill 默认按 C 级阈值告警

### 11.2 6K 系列三件套（静设备腐蚀监测 PIPELINE，positionType 61..64）

- [x] 11.2.1 创建 `skills/custom/ins-get-trend-data-6k/`：SKILL.md "Default Feature Mapping" 段改为：`positionType=62`（TH 探头）→ `["corrosionRate", "thinningRate", "thickness", "temperature"]`，`positionType=61` STA → `["value"]`；`run.sh` 调 `get_trend_data_6k_tool.py`
- [x] 11.2.2 创建 `skills/custom/ins-extract-trend-features-6k/`：在 SKILL.md 的 "Notes" 段增加："厚度时间序列建议同时输出窗口首末差值 (`thickness_loss`) 与线性回归斜率 (`thinning_rate_fit`)，与 InS 平台原始 `thinningRate` 字段交叉验证"
- [x] 11.2.3 创建 `skills/custom/ins-device-analysis-6k/`：SKILL.md 强调 "本 skill 仅返回 6K 静设备测点；旋转机组振动测点请使用 `ins-device-analysis`（8K 默认）或 `ins-device-analysis-2k`/`-9k`"

### 11.3 9K 系列三件套（往复 / 高端旋转机组 RC，positionType 91..99）

- [x] 11.3.1 创建 `skills/custom/ins-get-trend-data-9k/`：SKILL.md 默认特征：`positionType=93,94`（PBX/PBY 轴瓦振动）→ `["pp_value", "rms", "p_value", "speed"]`；其他 process 类 → `["value"]`；`run.sh` 调 `get_trend_data_9k_tool.py`
- [x] 11.3.2 创建 `skills/custom/ins-extract-trend-features-9k/`：SKILL.md 提示 "9K 序列由 client.py 自动注入 `density=high` / `includeFilter=history` / `typeList=<features>`，wrapper 与 skill 层无须手工拼装"
- [x] 11.3.3 创建 `skills/custom/ins-device-analysis-9k/`：SKILL.md 与现有 `reciprocating-fault-diagnosis` 保持调用契约一致（后者升级后由调 `ins-device-analysis` 改调本 skill）

### 11.4 6K 上层诊断 skill：static-equipment-corrosion-diagnosis

- [x] 11.4.1 创建 `skills/custom/static-equipment-corrosion-diagnosis/`：参考 `pump-fault-diagnosis` 形态，包含 `SKILL.md` + `references/diagnosis-rules.md`
- [x] 11.4.2 `SKILL.md` 描述静设备（管线 / 容器 / 塔器）腐蚀诊断的输入：6K 测点的 `corrosionRate` / `thinningRate` / `thickness` / `temperature` 时序 + 工艺联动数据；输出：腐蚀速率异常 / 壁厚预测寿命（基于线性外推）/ 减薄率突变 / 工艺温度耦合 4 个判定条 + 结构化结论
- [x] 11.4.3 `references/diagnosis-rules.md` 编写**占位规则集**（与 `pump-fault-diagnosis` 一致采用占位策略）：
  - `corrosion_rate_anomaly`：腐蚀速率超阈值（行业经验值 0.1 mm/y "中"、0.25 mm/y "高"、0.5 mm/y "极高"）
  - `thickness_remaining_life`：剩余壁厚 / 当前减薄率 → 预测寿命；< 2 年置 `high` 优先级
  - `thinning_rate_step_change`：减薄率窗口前后比值 > 1.5×，结合温度同步上升 → 推 `process_upset`
  - 在 SKILL.md "Status" 段标注 "占位版本：3 条占位规则用于端到端联调，完整规则评审需领域专家逐条评审现场样本"
- [x] 11.4.4 在 SKILL.md "Fault family code mapping" 段固化占位 code：`corrosion_rate_anomaly` / `thickness_remaining_life` / `thinning_rate_step_change` / `process_temperature_coupling`

### 11.5 skill 注册 & 索引更新

- [x] 11.5.1 检查 `skills/custom/` 是否存在索引文件（如 `skills/custom/README.md` 或 `skills/SKILLS.json`）；如有，把 10 个新 skill 的名称 + 一行描述追加进去；如无则跳过（**实测无索引文件，跳过**）
- [x] 11.5.2 检查 `agents/builtin/*/SOUL.md` 中现有 7 个 ins-* skill 的引用方式（如 `pump-fault-diagnosis` SOUL 是否枚举调用名）；如发现 SOUL 通过 skill 名称枚举控制可见性，则在 `pump-fault-diagnosis` SOUL 中显式声明 "数据获取走 `ins-*-2k` 系列"，在 `reciprocating-fault-diagnosis` SOUL 中声明 "走 `ins-*-9k` 系列"，避免上层误调 8K 默认 skill
- [x] 11.5.3 在 `backend/docs/HTTP_CONNECTORS.md`（§9.1 文档段已建立）追加一张表："10 个新 skill × 4 endpoint series × 适用设备类型"对照表，便于后续上层 SOUL 选择正确 skill

### 11.6 skill 单元测试（合并到 §8.1，本段只列实施清单）

- [x] 11.6.1 在 `backend/tests/`（或 `docker/sandbox/features-tool/tests/`，按既有 skill 测试位置选定）增加以下文件，每个文件覆盖对应 wrapper 的 `endpoint_series` 透传 + 默认 feature + 输出 shape：
  - `docker/sandbox/features-tool/tests/test_tools.py` 已合并覆盖 9 个 InS wrapper（`get_trend_data_*k` / `device_analysis_*k` / `extract_trend_features_*k`）
  - `backend/tests/test_skills_static_equipment_corrosion.py` 覆盖 10 个 skill 包装层（9 InS 数据获取 + 1 腐蚀诊断）：frontmatter / run.sh / fault-family code / 占位规则 id schema
- [x] 11.6.2 运行 `make test`（backend）+ `pytest docker/sandbox/features-tool/tests/`（features-tool）确认 0 回归（features-tool 9 passed / backend 新增 21 passed）
