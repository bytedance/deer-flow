## Why

设备日/周/月运行报告（`ai-report--daily/weekly/monthly` 三个智能体 + 同名 builtin 模板）目前 KPI、24h 趋势、告警全部由 `query_daily.py` / `query_weekly.py` / `query_monthly.py` 中的 `_demo_*` 函数基于 md5 哈希派生，与生产 InS 平台完全脱节。同 skill 树下 [`features-tool/ins/client.py`](docker/sandbox/features-tool/ins/client.py) 已经实现了完整的 `InsApiClient`（登录 / token 续期 / RSA 加密 / `get_components` / **`get_trend_data`** / 波形 / 轴心轨迹），并通过 `deer-flow-sandbox-features-tool:latest` 镜像挂在每个 docker sandbox 容器的 `/opt/features-tool`，`config.yaml` 已经把 `INS_USERNAME` / `INS_PASSWORD` / `FEATURES_TOOL_ROOT=/opt/features-tool` 注入到 sandbox env —— 故障诊断、`ins-get-trend-data` 等 7 个 skill 都已在生产使用。日/周/月报这三个最常用的入口偏偏没接，是这条真数据链路里唯一缺失的一段。

实测样本进一步揭示 InS 平台覆盖范围**远超原认知**：6k 路径已经提供 `corrosionRate` / `thinningRate` / `thickness` / `temperature` 四个静设备腐蚀监测维度（典型场景：带 TH 探头的容器、管线、塔器），不需要再外接 LIMS 实验室系统。原计划的"第二提案：接 LIMS / RBI / CMMS / 巡检"对应的腐蚀类 KPI 也由本提案统一通过 InS 真数据覆盖；剩余的 RBI 检验周期 / CMMS 工单 / 巡检点检数据另启提案处理（本提案不覆盖）。

## What Changes

- 在 `skills/custom/data-analyst/scripts/` 新增 `_ins_provider.py`：在 `sys.path` 注入 `FEATURES_TOOL_ROOT`（默认 `/opt/features-tool`），`from ins import InsApiClient, load_ins_settings`，封装一组同步辅助函数（`asyncio.run` 包裹），把"设备 ID 列表 + KPI 列表 + 时间范围"翻译成 `InsApiClient.get_components` + `InsApiClient.get_trend_data` 调用，再把返回的点级时序聚合为 `daily_data.json` 期望的 `current.kpis` / `current.hourly_runtime_rate` / `current.alarms` 形状。
- **扩展 `features-tool/ins/client.py`**：InS 平台实际有 4 套并行的实时趋势接口，路径不同、查询参数不同、响应 shape 不同：

  | 序列 | 路径 | 用途 | 响应 shape |
  |---|---|---|---|
  | 2k | `/ins-os-view/data/getTrendDataHis` | 旧版振动测点 | 扁平 `{datatime, value: float}` |
  | 6k | `/ins-os-view/sg6kData/getTrendDataHis` | **静设备腐蚀监测**（壁厚 / 腐蚀率 / 减薄率 / 温度） | 多 feature 嵌套：`value: [{key, name, unit, value: str}]` |
  | 8k | `/ins-os-view/sg8kData/getTrendDataHis` | 当前默认，旋转机组振动 / 温度 / 转速 | 扁平（`pp_value` / `value` / `speed` 等单字段） |
  | 9k | `/ins-os-view/sg9kData/getTrendDataHis` | 高端旋转机组（带 `density=high` / `typeList`） | 扁平，多 feature 一次拉 |

  本提案扩展 `InsApiClient`：
  
  (a) `slim_component` 在**测点节点**（不是机器节点）上多带 `endpoint_series` 字段（取值 `"2k"|"6k"|"8k"|"9k"`，未识别为 `None`），通过测点的 `positionType` / `type` 字段映射；
  
  (b) `get_trend_data` 新增 `endpoint_series`（必传，默认 `"8k"` 向后兼容）+ `factory_id`（**可选**，默认 `None` 不附加到 query，符合现有 8k 调用方实测不需要 `factoryId` 的事实）+ `density` / `include_filter` / `type_list` 等系列特异参数；
  
  (c) 新增 `parse_trend_response(rows, series)` 辅助：6k 系列把嵌套 feature 数组展平为 `{datatime, <key>: float}` 形式，与 2k/8k/9k 的扁平 shape 统一对齐。`_ins_provider.py` 在拉取组件树后**按测点的 `endpoint_series` 分桶**（同一台机器可能既有 6k 腐蚀测点又有 8k 振动测点），逐桶调用并按桶解析。

- 在 `_data_providers.py` 的 `_PROVIDER_FACTORIES` 注册三个 source 键：`daily` / `weekly` / `monthly`，每个 source 注册 `Demo*Provider`（重用现有 `_demo_*` 函数）和 `Ins*Provider`（调 `_ins_provider`）。路由开关：单个 env `DEER_FLOW_DATA_PROVIDER` 取值 `demo`（默认） / `ins`。
- 改造 `query_daily.py` / `query_weekly.py` / `query_monthly.py` 的 `fetch_day` / `fetch_week` / `fetch_month` 走 `fetch_with_fallback`，输出 JSON 顶层新增 `data_source`（`"ins"` / `"demo_fallback"`） + `data_notes: list[str]`；下游 `daily_kpi.py` / `weekly_kpi.py` / `monthly_kpi.py` 透传两字段。
- 在 `export_report.py:render_markdown` 顶部根据 `payload["data_source"]` 渲染横幅（"✅ 数据来源：InS 实时接入" / "⚠️ 当前使用演示数据（fallback）：<原因>"）；DSL 模板（`agents/builtin/report-templates/{daily,weekly,monthly}-equipment/default.yaml`）在 sections 数组首位增加一个 markdown section 指向 `data_source_banner`；三个 SOUL 文档在"生成报告"步骤里增加"必须保留首行横幅"约束。
- KPI → InS feature 映射规则在 `_ins_provider.py` 维护单一 `_KPI_FEATURE_MAP` 常量，**覆盖旋转机组 + 静设备腐蚀监测**两类：
  - 旋转：`vibration_level` / `bearing_temp` / `valve_temp` / `flow_rate` / `outlet_pressure` / `runtime_rate` / `alarm_count` / `downtime_count`（8k / 9k 系列）
  - 静设备腐蚀：`corrosion_rate`（6k 系列 `corrosionRate` 字段）/ `thickness_loss`（6k `thickness` 字段时间窗 first−last）/ `thinning_rate`（6k `thinningRate`）/ `process_temperature`（6k `temperature`）
  - `runtime_rate` 与 `alarm_count` 由底层 trend + `h_alarm/hh_alarm` 阈值客户端派生
- 文档：在 [`backend/docs/HTTP_CONNECTORS.md`](backend/docs/HTTP_CONNECTORS.md) 与 [`backend/CLAUDE.md`](backend/CLAUDE.md) 增加"设备报告 InS 数据源"小节，明确 `DEER_FLOW_DATA_PROVIDER` 为唯一开关、复用现有 `INS_*` 凭据、4 套 endpoint 与各自适用场景。
- **新增 10 个 skill 覆盖 2K / 6K / 9K 三个非 8K 设备序列**（与本提案合并，不分阶段）。背景：现有 7 个 ins-* skill 都默认走 8K（`InsApiClient.get_trend_data` 的 8k 默认路径），对 2K 机泵 / 6K 静设备 / 9K 往复机组只有 `pump-fault-diagnosis` / `reciprocating-fault-diagnosis` 两个上层诊断 skill 可用，**底层数据获取层（trend / extract-trend-features / device-analysis）在生产 skill 树里彻底缺失**。本提案补齐：
  - 2K 系列（机泵专用）：`ins-get-trend-data-2k` / `ins-extract-trend-features-2k` / `ins-device-analysis-2k`
  - 6K 系列（静设备腐蚀监测专用）：`ins-get-trend-data-6k` / `ins-extract-trend-features-6k` / `ins-device-analysis-6k`
  - 9K 系列（往复机组专用）：`ins-get-trend-data-9k` / `ins-extract-trend-features-9k` / `ins-device-analysis-9k`
  - 6K 上层诊断：`static-equipment-corrosion-diagnosis`（管线 / 容器 / 塔器的腐蚀速率异常 / 壁厚预测寿命 / 减薄率突变 / 工艺温度耦合分析；对标 `pump-fault-diagnosis` 的设备类型专用诊断 skill）
  
  10 个 skill 的实现统一通过 `from ins import InsApiClient` 调用 `endpoint_series=<series>` 参数，复用本提案给 client.py 加的 4 路径路由 / 解析 / `slim_component` 字段透出，因此无新增基础设施。每个 skill 包含 `SKILL.md` + 包装脚本（`features-tool/tools/<name>.py`，复用 `get_trend_data_tool.py` / `extract_trend_features_tool.py` / `device_analysis.py` 的模板加 `--series <2k|6k|9k>` 入参）+ 测试。
- **非破坏性**：`DEER_FLOW_DATA_PROVIDER` 未设置时默认仍走 demo；InS 调用任何形式失败（网络 / 401 / 字段缺失 / KPI 映射缺失）→ 自动 fallback demo 并把降级原因写入 `data_notes`，报告永远能出。现有 7 个 8K skill 零回归（新 kwargs 默认值与原行为等价）。

## Capabilities

### New Capabilities
- `equipment-report-data-provider`: 为 daily / weekly / monthly 三类设备报告查询脚本统一定义"InS 真数据优先 + 演示数据兜底"的 Provider 抽象、`InsApiClient` 调用契约、4 套 endpoint 序列与按测点路由策略、6k 嵌套响应解析规则、KPI → InS feature 映射规则、`data_source` 透传规则与 fallback 行为，使 SOUL 与 DSL 模板路径都能区分演示与真实数据。
- `ins-multi-series-skills`: 为 InS 平台 2K（机泵 PUMP）/ 6K（静设备 PIPELINE）/ 9K（往复机组 RC）三个非 8K 设备序列各建立一套专属 skill（trend / extract-trend-features / device-analysis 各 3 个 = 9 个）+ 6K 静设备腐蚀诊断上层 skill `static-equipment-corrosion-diagnosis`（合计 10 个）。每个 skill 通过 `endpoint_series=<series>` 显式指定，复用 `equipment-report-data-provider` 给 `InsApiClient` 加的 4 路径路由 / 解析 / `slim_component` 字段透出，使 `pump-fault-diagnosis`（2K）、`reciprocating-fault-diagnosis`（9K）等上层诊断 skill 与未来的 6K 上层 skill 可以正确分层调用，避免直接 import client.py 的破坏。

### Modified Capabilities
<!-- 当前 openspec/specs/ 中没有覆盖 ai-report / data-analyst skill 的 spec；本提案只新增能力，不修改既有 spec 的 requirement。 -->

## Impact

- **代码（skills 层，新增）**：
  - `skills/custom/data-analyst/scripts/_ins_provider.py`（新文件，~300 行 —— 比初版多 50 行用于 6k 响应解析与按测点分桶）
  - **9 个数据获取层 skill 目录**（每个含 `SKILL.md` + 测试 fixtures）：`skills/custom/ins-get-trend-data-{2k,6k,9k}/`、`skills/custom/ins-extract-trend-features-{2k,6k,9k}/`、`skills/custom/ins-device-analysis-{2k,6k,9k}/`
  - **1 个上层诊断 skill 目录**：`skills/custom/static-equipment-corrosion-diagnosis/`（含 `SKILL.md` + 规则配置 + 测试 fixtures，对标 `pump-fault-diagnosis` 的形态）
- **代码（features-tool，新增 tool 包装脚本）**：基于现有 3 个 tool 模板（`get_trend_data_tool.py` / `extract_trend_features_tool.py` / `device_analysis.py`）派生 9 个序列专属 wrapper：`docker/sandbox/features-tool/tools/{get_trend_data,extract_trend_features,device_analysis}_{2k,6k,9k}_tool.py`，统一接受 `--series <2k|6k|9k>` 入参，内部调用 `InsApiClient.get_trend_data(..., endpoint_series=<series>)` 或 `slim_component`（按 series 过滤）。
- **代码（skills 层，修改）**：`_data_providers.py`、`_data_provider_impls.py`、`query_daily.py`、`query_weekly.py`、`query_monthly.py`、`daily_kpi.py`、`weekly_kpi.py`、`monthly_kpi.py`、`export_report.py`、`report_scripts.yaml`（如需登记新 KPI 元数据）。
- **代码（features-tool，修改）**：`docker/sandbox/features-tool/ins/client.py` —— `slim_component` 输出新增 `endpoint_series`；`get_trend_data` 新增 `endpoint_series` / 可选 `factory_id` / `density` / `include_filter` / `type_list` 参数与 4 路径路由；新增 `parse_trend_response(rows, series)` 辅助。这是本提案唯一**需要修改 features-tool** 的地方（与原 Non-Goal "不改 features-tool" 的例外）。
- **代码（agents builtin）**：`ai-report--daily/SOUL.md`、`ai-report--weekly/SOUL.md`、`ai-report--monthly/SOUL.md`；`report-templates/daily-equipment/default.yaml`、`weekly-equipment/default.yaml`、`monthly-equipment/default.yaml` —— 仅追加首行横幅 section。
- **后端（无改动）**：`data_runner.py` 已透传 sandbox env；`config.yaml` 已注入 `INS_USERNAME` / `INS_PASSWORD` / `FEATURES_TOOL_ROOT`。**features-tool 代码改动需要重建 docker sandbox 镜像 `deer-flow-sandbox-features-tool:latest` 并替换 docker registry / 本地 tag**（参考 [docker/sandbox/README.md](docker/sandbox/README.md) 的 `docker build` 命令）。
- **测试**：
  - 新增 `backend/tests/test_ai_report_daily_ins_provider.py` / `test_ai_report_weekly_ins_provider.py` / `test_ai_report_monthly_ins_provider.py`，覆盖 demo 默认路径、InS 成功（mock `InsApiClient` 的 4 套响应 shape）、InS 失败回退、KPI 映射正确性、按测点分桶正确性、6k 嵌套响应解析、`data_source` 字段透传、横幅渲染
  - 新增 10 个 skill 各自的单元测试：tool 包装脚本路径路由、`endpoint_series` 透传、2K 中文 `name` 经 `_TWO_K_NAME_KEY_MAP` 解析、6K `key` 字段展平、9K `density=high` 拼装、`alarm_thresholds` 透出
- **依赖**：零新增第三方依赖；InS 调用通过已存在的 `httpx`（`features-tool` 已 pin）。
- **运维 / 部署**：要切换到真数据，运维只需在 Gateway env 加 `DEER_FLOW_DATA_PROVIDER=ins`（其它 InS 凭据已配齐）。未配置则保持 demo，演示环境零影响。
- **沙箱模式约束**：本变更**仅在 docker sandbox 模式（`AioSandboxProvider`）下生效**，因为只有该模式下 `/opt/features-tool` 与 `INS_*` env 才存在；local sandbox 模式下 `_ins_provider.py` 检测到 import 失败会自动 fallback demo，并在 `data_notes` 里写入"local sandbox: features-tool 不可用"。
- **范围说明**：本提案接入的是 **InS 平台覆盖的全部 KPI 维度**（旋转机组 + 静设备腐蚀监测）+ **2K / 6K / 9K 三个非 8K 序列的完整 skill 套件**（10 个 skill 一次性出齐）。RBI 检验周期、CMMS 工单、巡检 / 点检记录等 InS 不覆盖的数据源**不在本提案范围**，待后续独立提案；本提案不影响也不阻塞那些 KPI 走 demo。
