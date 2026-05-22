## Context

`docker/sandbox/features-tool/ins/client.py` 中的 `InsApiClient` 已经是一个完整的 InS（神固云）平台 SDK，覆盖登录、token 续期、组件树、历史趋势、波形、轴心轨迹，并通过 `deer-flow-sandbox-features-tool:latest` 镜像把 `features-tool/` 拷到每个 docker sandbox 容器的 `/opt/features-tool`。`config.yaml` 已经把 `INS_USERNAME` / `INS_PASSWORD` / `FEATURES_TOOL_ROOT=/opt/features-tool` 注入 sandbox env。同 skill 树下的 `ins-get-trend-data` / `ins-device-analysis` / `ins-extract-*-features` / `pump-fault-diagnosis` 等 7 个 skill 已在生产使用 `InsApiClient.get_trend_data` / `get_components` 拿真数据。日 / 周 / 月报却还在 `_demo_*` 哈希派生 —— 这是真数据链路里仅剩的、最容易补上的一段。

`_data_providers.py` 已经为另外 5 个 source（trend / fault_context / failure_data / closure_items / inspection）建好 Demo / Http 双轨与 `fetch_with_fallback` 路由，本变更复用其架构。但本变更**不再走 HTTP**：`Ins*Provider` 直接 import `from ins import InsApiClient`，不需要运维侧自建新 endpoint。

利益相关方：

- 设备运行报告的最终用户 —— 必须能在报告里立即看出今天看到的是 InS 真实数据还是演示数据
- 后端运维 —— 通过单个 env 开关 `DEER_FLOW_DATA_PROVIDER=ins` 切换，所有 InS 凭据已配齐，零额外配置
- 平台开发 —— 与既有 `ins-*` skill 路径一致，不引入新依赖、不重建 sandbox 镜像

## Goals / Non-Goals

**Goals:**

- 为 `daily` / `weekly` / `monthly` 三个 source 在 `_PROVIDER_FACTORIES` 注册 `Demo*Provider` + `Ins*Provider`，路由由 `DEER_FLOW_DATA_PROVIDER` env 决定，默认 `demo`
- 新增单一适配模块 `_ins_provider.py` 封装"InS API → daily/weekly/monthly payload"的所有翻译逻辑，三个 Provider 类共用
- `query_daily.py` / `query_weekly.py` / `query_monthly.py` 的对外入口切换到 `fetch_with_fallback`；输出 JSON 顶层加 `data_source`（`"ins" | "demo_fallback"`）+ `data_notes: list[str]`
- KPI → InS feature 映射规则与 `ins-get-trend-data/SKILL.md` 默认表对齐，新增的 `runtime_rate` / `alarm_count` 派生逻辑写在客户端
- `export_report.render_markdown` 在首行渲染数据源横幅；DSL 与 SOUL 双轨都不可绕过
- InS 调用任何形式失败（网络 / 401 / 字段缺失 / 设备 ID 在 InS 中不存在 / KPI 映射缺失 / `features-tool` 不可 import）→ 自动 fallback demo + 写 `data_notes`
- 全部回归测试（`test_ai_report_daily_*`、`test_ai_report_weekly_*`、`test_ai_report_monthly_*`、`test_builtin_report_templates`）保持绿灯

**Non-Goals:**

- 不改后端 `data_runner.py` / `report_templates/schema.py` / DSL 解析器
- ~~不重建 docker sandbox 镜像~~ → **本提案需要重建**：因 `features-tool/ins/client.py` 改动了 `slim_component` 输出与 `get_trend_data` 路由，需重建 `deer-flow-sandbox-features-tool:latest`
- ~~不改 `features-tool/ins/client.py`~~ → **本提案需要改**：见 D10
- 不接入 InS 之外的 CMMS / TSDB（本次只对接已经在用的 InS）
- 不在 local sandbox 模式下提供真数据 —— 该模式 `/opt/features-tool` 不存在，`_ins_provider` 会 graceful fallback demo
- 不重构 `_demo_*` 函数签名（保持向后兼容）
- 不动前端 GenUI 组件（横幅在 markdown 里）
- 不处理 InS 不覆盖的设备数据源 —— RBI 检验周期、CMMS 工单、巡检 / 点检记录等留待后续独立提案接 LIMS / RBI / CMMS / 巡检系统，本提案不阻塞那些 KPI 走 demo

## Decisions

### D1：复用 InsApiClient，不再自造 HTTP endpoint

`Ins{Daily,Weekly,Monthly}Provider` 直接 `from ins import InsApiClient, load_ins_settings`，不走 `_data_providers.HttpEndpoint` 那条路径。

**理由**：

- `InsApiClient` 已经在生产使用、有鉴权 / 续期 / 错误处理；自造 HTTP 中间层只会重复一遍这些代码
- 凭据 (`INS_USERNAME` / `INS_PASSWORD`) 和镜像挂载 (`/opt/features-tool`) 已经在 `config.yaml` 与 `Dockerfile` 配齐 —— 运维零额外配置
- 与 `ins-get-trend-data` / `ins-device-analysis` 等 7 个 skill 同构，未来读这块代码的人无需理解额外抽象

**替代方案考虑**：

- *方案 B（HTTP endpoint，老版方案）*：让运维侧搭一个 `DEERFLOW_DAILY_URL` HTTP 服务作为聚合层。被否：要让运维多起一个服务、配一套 token、与 InS 凭据冗余；可观测性差。
- *方案 C（在 backend 包一层 service 调 InsApiClient）*：被否：违反 harness/app 边界（`features-tool` 在 sandbox 里），且需要在 backend 重复维护 InS 凭据。

### D2：单一开关 env 取代双开关

只用 `DEER_FLOW_DATA_PROVIDER` 一个 env：取值 `demo`（默认）或 `ins`。不再使用原方案的 `DEERFLOW_DAILY_URL` / `_TOKEN` 等。

**理由**：

- `INS_USERNAME` / `INS_PASSWORD` 已经在 sandbox env 中存在，不需要再加 source-specific URL/Token
- 单开关减少误配组合数（原方案 2³ × 2 = 16 种组合，现在 2 种）
- "切真" 的语义更直接：`DEER_FLOW_DATA_PROVIDER=ins`

### D3：新增单一适配模块 `_ins_provider.py`

把 `daily` / `weekly` / `monthly` 三个 Provider 共用的"InS → payload"翻译逻辑集中到一个新文件 `skills/custom/data-analyst/scripts/_ins_provider.py`，三个 `Ins*Provider` 类只是不同时间窗 + 不同 KPI 维度的薄壳。

**理由**：

- KPI → InS feature 映射、`get_components` 结果展平、`get_trend_data` 时序聚合（按小时 / 按日 / 按月）这套逻辑在三个时间粒度上 90% 重复
- 集中放一处便于单元测试，三个 Provider 类各 30 行就能 cover

**模块导出**：

```python
def fetch_daily_payload(date_str, equipment_ids, kpi_keys, eq_type, compare_with, equipment_meta) -> dict
def fetch_weekly_payload(week_start, equipment_ids, kpi_keys, eq_type, compare_with, ...) -> dict
def fetch_monthly_payload(report_month, equipment_ids, kpi_keys, eq_type, compare_with, ...) -> dict
def is_features_tool_available() -> bool   # 检测 sys.path 注入是否成功
```

### D4：sys.path 注入 FEATURES_TOOL_ROOT

`_ins_provider.py` 顶部：

```python
_FEATURES_TOOL_ROOT = os.environ.get("FEATURES_TOOL_ROOT", "/opt/features-tool")
if _FEATURES_TOOL_ROOT and Path(_FEATURES_TOOL_ROOT).is_dir():
    sys.path.insert(0, _FEATURES_TOOL_ROOT)
try:
    from ins import InsApiClient, load_ins_settings  # noqa: E402
    from ins.client import datetime_input_to_ms      # noqa: E402
    _FEATURES_TOOL_AVAILABLE = True
except ImportError:
    _FEATURES_TOOL_AVAILABLE = False
```

**理由**：

- 与 `ins-get-trend-data/scripts/run.sh` 的 `cd $ROOT; PYTHONPATH=. python3 ...` 等价，但适配 Python import 而不是子进程
- import 失败时 `_FEATURES_TOOL_AVAILABLE=False`，Provider 抛 `ImportError` 触发 fallback demo（不让脚本崩）
- local sandbox 模式 / 单元测试环境 / `features-tool` 未挂载场景全部走 fallback

### D5：异步 → 同步桥接

`InsApiClient` 是 `async def`，但 `query_daily.py` / `query_weekly.py` / `query_monthly.py` 当前是纯同步脚本。在 `_ins_provider.py` 内用 `asyncio.run` 包裹：

```python
def fetch_daily_payload(...) -> dict:
    return asyncio.run(_async_fetch_daily(...))
```

**理由**：

- 三个查询脚本本身在子进程里被 `data_runner` 串行启动，没有外层 event loop —— `asyncio.run` 安全
- 与 `features-tool/tools/get_trend_data_tool.py:main()` 的做法一致
- 避免把整个查询脚本改造成 async（影响 `_demo_*` 路径）

**替代方案考虑**：

- *方案 B*：把 `query_daily.py` 改造成 `async def main()` —— 被否：影响所有 demo 路径测试，破坏向后兼容
- *方案 C*：在 `InsApiClient` 上加同步 wrapper —— 被否：违反"不改 features-tool"的非目标

### D6：KPI → InS feature 二级映射表（含 6k 静设备腐蚀监测）

映射放在 `_ins_provider.py` 的 `_KPI_FEATURE_MAP` 常量里。本提案接入的是 **InS 平台覆盖的全部 KPI 维度**：旋转机组（2k/8k/9k 系列）+ 静设备腐蚀监测（6k 系列）。

| KPI key | 来源测点 | InS series | feature 路径 | 派生方法 |
|---|---|---|---|---|
| `vibration_level` | `type=83` 振动测点 | 8k / 9k | `pp_value`（无"波形"后缀） | 全天均值 |
| `bearing_temp` | `type=82` 含"轴承"关键字 | 8k | `value` | 全天均值 |
| `valve_temp` | `type=82` 含"阀"关键字 | 8k | `value` | 全天均值 |
| `flow_rate` | `type=82` 含"流量"关键字 | 8k | `value` | 全天均值 |
| `outlet_pressure` | `type=82` 含"出口压力"关键字 | 8k | `value` | 全天均值 |
| `runtime_rate` | `type=81` 转速测点 | 8k / 9k | `speed` | `count(speed>0) / count(*)` |
| `alarm_count` | 任意测点 `value` 与 `h_alarm` / `hh_alarm` 比对 | 8k / 9k | `value` + 阈值 | 越限次数 |
| `downtime_count` | `type=81` 转速 | 8k / 9k | `speed` | `speed` 从 >0 落到 0 的次数 |
| `corrosion_rate` | `positionType=62` 等腐蚀监测测点 | **6k** | `corrosionRate`（嵌套数组中按 `key` 选） | 全天均值（字符串转 float） |
| `thickness_loss` | `positionType=62` 腐蚀测点 | **6k** | `thickness`（嵌套数组） | 时间窗 first − last（mm） |
| `thinning_rate` | `positionType=62` 腐蚀测点 | **6k** | `thinningRate`（嵌套数组） | 全天均值 |
| `process_temperature` | `positionType=62` 腐蚀测点 | **6k** | `temperature`（嵌套数组） | 全天均值；空字符串视为缺数据 |
| `output` / `energy_consumption` 等 | InS 暂无对应点 | — | — | **不在表中 → fallback demo + warning** |

**6k 响应嵌套结构**：与 8k 的扁平 `{datatime, value: float}` 不同，6k 响应中每条 `value` 是数组：

```json
{
  "datatime": 1777602477303,
  "value": [
    {"key": "corrosionRate", "name": "腐蚀率", "unit": "mm/a", "value": "7.77..."},
    {"key": "thinningRate",  "name": "减薄率", "unit": "%",    "value": "0.057..."},
    {"key": "thickness",     "name": "厚度",   "unit": "mm",   "value": "9.666"},
    {"key": "temperature",   "name": "温度",   "unit": "℃",    "value": ""}
  ]
}
```

由 `parse_trend_response(rows, series="6k")` 展平为 `[{datatime, corrosionRate, thinningRate, thickness, temperature}, ...]`，所有字段转 float（空字符串 → `None`）。空字段不计入均值。

**实施方式**：`_ins_provider.py` 先尝试 InS 拉所有 mappable KPI；任何 mappable KPI 失败 → 整体 fallback demo；任何 unmappable KPI（不在表中）→ 整份报告标记为 `demo_fallback`，notes 里说"KPI 'output' 在 InS 中无映射"。**不混合两种数据源**，避免一份报告里既真又假混淆用户。

### D7：`data_source` 字段写在顶层

与原方案一致：`daily_data.json` / `weekly_data.json` / `monthly_data.json` 顶层加 `data_source: "ins" | "demo_fallback"` + `data_notes: list[str]`。透传到 `*_kpi.json` 和 markdown 横幅。

### D8：横幅渲染由 Python 而非 LLM 兜底

`export_report.render_markdown` 在 markdown 第一行强制写入：

- `data_source == "ins"` → `> ✅ 数据来源：InS 实时接入`
- `data_source == "demo_fallback"` → `> ⚠️ 当前使用演示数据（fallback）。原因：<data_notes[0] or "未配置真实数据源（DEER_FLOW_DATA_PROVIDER 未设置为 ins）">`

DSL 路径通过新增的 sections[0] markdown 块拿同款字符串；SOUL 路径要求 LLM 在拼接 markdown 时保留 Python 已经渲染好的首行。

### D9：测试用 `unittest.mock` 打 InsApiClient

测试中通过 `monkeypatch` 替换 `_ins_provider._async_fetch_daily` 内部调用的 `InsApiClient` 类，避免真正发起 HTTP；预制 `get_components` / `get_trend_data` 的固定返回，验证：

1. demo 默认路径
2. InS 成功 → `data_source == "ins"`
3. InS 网络异常 → fallback demo + `data_notes`
4. InS 返回为空 → fallback demo + `data_notes`
5. KPI 不在映射表 → fallback demo + `data_notes`
6. `features-tool` 未挂载 / `import ins` 失败 → fallback demo + `data_notes`
7. `data_source` / `data_notes` 透传到 `*_kpi.json`
8. 横幅在 `render_markdown` 第一行

### D10：4-endpoint 按测点路由 + 2k/6k 嵌套响应解析 + factoryId 可选

InS 平台对不同采集设备序列使用 4 套并行的实时趋势接口；机器层 `type` ↔ endpoint series 的对应关系**来自 InS 服务端 `MachineType` Java 枚举（已确认权威）**：`type=1`(MAC) → 8K，`type=4`(PUMP) → 2K，`type=6`(PIPELINE) → 6K，`type=9`(RC) → 9K。枚举里另列出的 `type=16`(VALVE 疏水阀，对应 7K) 与 PUMP 也可能命中的 5K 接口本提案**不在范围**，由 8K 兜底处理（与现有 7 个生产 skill 行为一致），后续要接时独立提案。

| 序列 | 路径 | 机器层 `type` | 设备类别 | 用途 | 响应 shape |
|---|---|---|---|---|---|
| 2K | `/ins-os-view/data/getTrendDataHis` | 4 (PUMP) | 机泵 | 旧版多 feature 振动测点（速度有效值 / 加速度峰值 / 包络等） | **嵌套** `{datatime, value: [{unit, name, value}, ...]}`（无 `key`，靠中文 `name` 识别） |
| 6K | `/ins-os-view/sg6kData/getTrendDataHis` | 6 (PIPELINE) | 静设备 管线 / 容器 | **静设备腐蚀监测**（壁厚 / 腐蚀率 / 减薄率 / 温度） | **嵌套** `{datatime, value: [{key, name, unit, value}, ...]}` |
| 8K | `/ins-os-view/sg8kData/getTrendDataHis` | 1 (MAC) | 旋转机组 | 当前 client 默认，旋转机组振动 / 温度 / 转速 | 扁平 `{datatime, pp_value/value/speed/...}` |
| 9K | `/ins-os-view/sg9kData/getTrendDataHis` | 9 (RC) | 往复机组 | 高端往复 / 高端旋转机组（多 feature 一次拉，`typeList=speed,rms` 等） | 扁平 |

**实测 2k 样本**（positionType=23，泵前轴承）：

```json
{
  "positionType": 23,
  "equipmentId": 200415124801173,
  "posName": "泵前轴承_A",
  "vRmsBValue": 3.5, "vRmsCValue": 7.5, "vRmsDValue": 18.0,
  "gBValue": 2.86,   "gDValue": 14.69,
  "aPeakBValue": 28.0, "aPeakCValue": 60.0,
  "kurtosisBValue": 3.0, "kurtosisCValue": 5.0, "kurtosisDValue": 10.0,
  "index": [{"unit": "mm/s", "name": "速度有效值"}, {"unit": "m/s²", "name": "加速度峰值"}],
  "value": [
    {"datatime": 1778635456000, "value": [
      {"unit": "mm/s", "name": "速度有效值", "value": 0.3006},
      {"unit": "m/s²", "name": "加速度峰值", "value": 1.8318}
    ]}
  ]
}
```

2k 响应的关键差异：(a) 嵌套数组的元素**没有** `key` 字段，feature 通过中文 `name` 识别；(b) 顶层测点元数据携带 **B / C / D 三级阈值**（B = alert / C = alarm / D = danger），每个 feature 都有独立的 BValue/CValue/DValue 字段（`vRmsBValue/CValue/DValue`、`gBValue/CValue/DValue`、`kurtosisBValue/CValue/DValue`、`aPeakBValue/CValue/DValue` 等）；(c) 顶层 `index` 是 legend 数组，描述内部 `value` 数组的排列。

**关于按测点路由（不是按机器路由）**：实测 6k 样本（P-203A 出口 TH 测点）是一个**腐蚀监测探头**，与同一台机器上的振动测点完全可能共存于不同 endpoint 序列。`slim_component` 因此把 `endpoint_series` 字段放在**测点（point）层**而不是机器（machine）层。同一份 `_ins_provider.fetch_*_payload(...)` 调用可能同时打 6k 和 8k 两套 endpoint。

**识别策略**（按测点字段优先级）：

1. **测点层 `positionType` 字段映射**（**依据 InS 服务端 `PointPositionType` Java 枚举，权威**；每个序列下"过程量(STA)"还有子类型，遇到再加入）：
   - `positionType in {22..30}` → `2k`
     - 22=STA (W203过程量)、23=VIB (W203振动，实测 `posName="泵前轴承_A"`)、24=OTHER_VIB (第三方振动)、25=STA_GENERAL (第三方过程量)、26=M_VIB (W205主轴振动)、27=S_VIB (W205辅轴振动)、28=STA_W205 (W205过程量)、29=REV_SPEED (第三方转速)、30=MAGNETIC_FLUX (磁通量)
   - `positionType in {61..64}` → `6k`
     - 61=STA (过程量)、62=TH (在线测厚，实测 P-203A 出口_TH)、63=P (腐蚀探针)、64=OTHER_TH (离线检测)
   - `positionType in {81..83}` → `8k`
     - 81=KEY (键相 / 转速参考)、82=STA (过程量)、83=VIB (振动)
     - **保留现有 8k STA(82) 子类型识别**：`posName` 含"轴承" → `bearing_temp`、含"阀" → `valve_temp`、含"流量" → `flow_rate`、含"出口压力" → `outlet_pressure`
   - `positionType in {91..99}` → `9k`
     - 91=JSZD (机身振动)、92=SZT (十字头振动)、93=PBX (活塞杆偏摆X)、94=PBY (活塞杆沉降/偏摆Y)、95=GTZD (缸头振动)、96=GCYL (盖侧压力)、97=KEY (键相)、98=STA (过程量，子类型遇到再加入)、99=ZCYL (轴侧压力)
   - 其它 → 未识别
2. **机器层 `type` 字段补充**（**依据 InS 服务端 `MachineType` Java 枚举，权威**）：当测点无 `positionType` 或落在未知区间，回退到机器层 `type`：
   - `type=1`（MAC，旋转机组）→ `8k`
   - `type=4`（PUMP，机泵）→ `2k`
   - `type=6`(PIPELINE，静设备 管线/容器) → `6k`
   - `type=9`（RC，往复机组）→ `9k`
   - 其它 `type` 值（含 `type=16` VALVE 疏水阀，对应服务端 7K 接口；以及 PUMP 走 5K 的情况）→ 未识别 → 走步骤 3 的 8k 兜底（本提案不接入 5K / 7K，相关 KPI 留待独立提案）
3. **兜底**：识别失败 → 默认走 **8k 路径**，因为现有 7 个生产 skill 已经验证 8k 路径对多种设备能 work，不报错也不 fallback demo

**关于 `factoryId`**：调研发现 `factoryId` **不在 `getComponentByMachineIds` 响应中**（实测 2k / 9k 两条样本均无该字段，6k 是 trend 响应不含组件信息）。前端 URL 中传 `factoryId` 可能只是 UI 上下文冗余 —— `InsApiClient.get_trend_data` 当前的 8k 调用方（`ins-get-trend-data` / `pump-fault-diagnosis` 等 7 个生产 skill）从未传过 `factoryId` 且能正常拉数据。本提案把 `factoryId` 设为**可选 kwarg**：默认 `None` → 不附加到 query；如未来发现某条路径 server 强制 → 通过 env `INS_FACTORY_ID` 显式提供。

**关于 2k / 6k 响应解析**：两个序列都返回嵌套 `value` 数组，但内部 feature 标识方式不同：

- **6k**（feature 用 `key` 字段）：

  ```json
  {"datatime": 1777602477303, "value": [
    {"key": "corrosionRate", "name": "腐蚀率",   "value": "7.77"},
    {"key": "thinningRate",  "name": "减薄率",   "value": "0.057"},
    {"key": "thickness",     "name": "厚度",     "value": "9.666"},
    {"key": "temperature",   "name": "温度",     "value": ""}
  ]}
  ```

- **2k**（feature 仅有中文 `name`，**无 `key`**）：

  ```json
  {"datatime": 1778635456000, "value": [
    {"unit": "mm/s", "name": "速度有效值", "value": 0.3006},
    {"unit": "m/s²", "name": "加速度峰值", "value": 1.8318}
  ]}
  ```

而 8k / 9k 是真正的扁平 shape：`{datatime, pp_value/value/speed/rms/...}`。为统一上层聚合逻辑，新增 `parse_trend_response(rows, series)` 辅助：

- `series in {"8k","9k"}` → 直返 rows
- `series == "6k"` → 用 `key` 字段把内部数组展平为顶层 `{datatime, corrosionRate, thinningRate, thickness, temperature, ...}`；字符串值 `try/except float(...)`，`""` 转 `None`
- `series == "2k"` → 用 `_TWO_K_NAME_KEY_MAP` 把中文 `name` 翻译成 ASCII key 后展平：`"速度有效值" → v_rms`、`"加速度峰值" → a_peak`、`"加速度有效值" → a_rms`、`"位移峰峰值" → pp_value`、`"包络谱峰值" → envelope_peak`、`"峭度" → kurtosis`、`"裕度" → margin`、`"脉冲指标" → pulse`、`"波形指标" → wave`；未知 `name` 原样作 key（debug log，便于补样本时直接发现）

**实施方式**：

1. 扩展 `features-tool/ins/client.py:slim_component(...)`：**测点节点**新增字段 `endpoint_series: str | None`，由测点的 `positionType` → series 映射决定（依据 InS 服务端 `PointPositionType` Java 枚举：`{22..30}→2k`、`{61..64}→6k`、`{81..83}→8k`、`{91..99}→9k`）；若 None 则回退到机器层 `type` 映射（依据 InS 服务端 `MachineType` Java 枚举：`1→8k`、`4→2k`、`6→6k`、`9→9k`；其它 type 含 `16→7k`、PUMP 走 5K 等本提案不接入的情况）；仍 None 则走 8k 兜底。**8k STA(82) 子类型识别保留现状**：测点上不写死 KPI key，由 `_KPI_FEATURE_MAP` 在 `_ins_provider` 内按 `posName` 含"轴承"/"阀"/"流量"/"出口压力"分流。**2k 测点层额外透传 B/C/D 三级阈值**（`vRmsBValue/CValue/DValue`、`gBValue/CValue/DValue`、`kurtosisBValue/CValue/DValue`、`aPeakBValue/CValue/DValue`、`pulseBValue/CValue/DValue`、`marginBValue/CValue` 等），按 `alarm_thresholds: {<feature>: {B, C, D}}` 结构透出；以及 `index`（legend 数组）。机器节点保留 `samplerId` 透传以备诊断

2. 扩展 `InsApiClient.get_trend_data(...)`：

   ```python
   _ENDPOINT_PATH_BY_SERIES = {
       "2k": "/ins-os-view/data/getTrendDataHis",
       "6k": "/ins-os-view/sg6kData/getTrendDataHis",
       "8k": "/ins-os-view/sg8kData/getTrendDataHis",
       "9k": "/ins-os-view/sg9kData/getTrendDataHis",
   }

   _TWO_K_NAME_KEY_MAP = {
       "速度有效值": "v_rms",
       "加速度峰值": "a_peak",
       "加速度有效值": "a_rms",
       "位移峰峰值": "pp_value",
       "包络谱峰值": "envelope_peak",
       "峭度": "kurtosis",
       "裕度": "margin",
       "脉冲指标": "pulse",
       "波形指标": "wave",
   }

   async def get_trend_data(
       self,
       component_id: str,
       start_ms: int,
       end_ms: int,
       features: list[str],
       *,
       endpoint_series: str | None = "8k",
       factory_id: str | None = None,
       density: str | int = 1,
       include_filter: str | None = None,
       type_list: str | None = None,
   ) -> list[dict]:
       series = endpoint_series or "8k"
       path = _ENDPOINT_PATH_BY_SERIES[series]
       params = {"gpids": component_id, "startTime": start_ms, "endTime": end_ms, "density": density}
       if factory_id is not None:
           params["factoryId"] = factory_id
       if series == "9k":
           params["includeFilter"] = include_filter or "history"
           params["typeList"] = type_list or ",".join(features)
       rows = await self._get_json(path, params=params)
       return parse_trend_response(rows, series=series)
   ```

3. 新增模块级 `parse_trend_response(rows, series)`：2k / 6k 时展平嵌套 `value` 数组（2k 走中文 name 映射、6k 走 `key` 字段），8k / 9k 直返。所有内部 `value` 用 `try/except float(...)`；空字符串 / 非数字 → `None`，上层聚合跳过

4. `_ins_provider.py` 在拉到组件树后**按测点的 `endpoint_series` 分桶**调用 `get_trend_data`；同一台机器跨 6k + 8k（或 2k + 6k 等任意组合）两桶完全合法

5. **`alarm_count` 派生使用 B/C/D 三级阈值**：对 2k 测点优先使用 `_aggregate_trend_to_kpi` 中按 KPI 类型（vibration / acceleration / kurtosis / pulse）选对应 C 级阈值（`vRmsCValue` / `gCValue` / `kurtosisCValue` / `pulseCValue`）作为"告警"阈值，D 级（`vRmsDValue` 等）作为"危险"阈值。8k 测点仍用 `h_alarm` / `hh_alarm`（与现有 `slim_component` 行为一致）。`alarm_count` 默认对应 ≥ C 级阈值的越限次数；如果 KPI 显式要求 danger 级则升级到 D

6. 新增可选 env `INS_FACTORY_ID`：若设置，`_ins_provider` 把该值透传给所有 `get_trend_data` 调用。未设置则保持默认 `None`

**理由**：

- 按测点路由 → 表达力够（"压缩机机壳装了腐蚀探头"场景 work）；按机器路由 → 无法表达
- 把 2k 与 6k 解析统一进 `parse_trend_response` → 上层 `_ins_provider` 只面对扁平字典，单元测试只需 mock 路径返回；2k 中文 name 映射放 client.py 是因为这是 InS 平台契约，不应让每个 skill 各自维护
- factoryId 可选 → 与现有调用方零回归，符合实测反向证据
- 兜底走 8k → 报告永远能出，与"graceful fallback"原则一致

**替代方案考虑**：

- *方案 B（按机器路由）*：被否，无法表达同机器跨 endpoint 场景
- *方案 C（factoryId 必传）*：被否，违反现有 8k 调用方实测可省的事实
- *方案 D（2k/6k 解析在 `_ins_provider.py`）*：被否，与 client 的"返回标准化数据"职责不符
- *方案 E（2k 按 `index` legend 的位置匹配 feature）*：被否，`index` 顺序与 `value` 内顺序不保证一致；按 `name` 命中更稳健，未知 name 走原样透传比硬编码位置更安全

**风险**：见 R6 / R7 / R8 / R9。

## Risks / Trade-offs

- **[Risk] InS 平台某些设备 ID 在 `getComponentByMachineIds` 找不到（用户在前端 `device-selector-multi` 选了 InS 不识别的 ID）** → Mitigation：`_ins_provider` 先用 `get_components` 校验；任意一台设备查不到 → 整份报告 fallback demo，`data_notes` 写明"<id> 在 InS 中不存在"
- **[Risk] InS API 偶发 401 / 502** → Mitigation：`InsApiClient._get_json` 已经实现 401 自动重登一次，超过重试仍失败 → fallback demo
- **[Risk] type=82 测点的"轴承温度 / 阀温 / 流量"靠**关键字识别**会漏点或错配** → Mitigation：D6 映射表暂用关键字，failure case 写入 `data_notes`；后续 D6.1 可让 ai-report 在表单里让用户为 KPI 显式选测点（暂不做）
- **[Risk] 运维误开 `DEER_FLOW_DATA_PROVIDER=ins` 但 InS 凭据失效** → Mitigation：第一次 `login()` 失败即 fallback demo，所有报告依然能出，`data_notes` 写明 401；运维通过 telemetry 看降级率
- **[Risk] `asyncio.run` 在已有 event loop 的 caller 里会报错** → Mitigation：`data_runner` 子进程里没有外层 loop，本路径安全；但若未来 `query_daily.py` 被改成 async caller 调用，需要换 `nest_asyncio` 或 `loop.run_until_complete`
- **[Trade-off] 三种时间粒度共用 `_ins_provider.py` → 单文件可能较长** → 接受，~200 行；若超过 400 行再拆 `_ins_provider/{daily,weekly,monthly}.py`
- **[Trade-off] 静设备 KPI（腐蚀 / 壁厚）InS 没采集 → 用户选这些 KPI 的报告永远是 demo** → 接受，`data_notes` 透明告知；后续 D6 扩展再补
- **[Trade-off] 不在 local sandbox 跑 InS** → 接受，与 `ins-*` skill 一致；本地开发想验证真数据需起 docker sandbox
- **[Risk R6] 测点路由识别不到 `endpoint_series`**（`positionType` 落在未知区间且机器层 `type` 不在 `{1, 4, 6, 9}`，例如 `type=16` 疏水阀走 7K 接口、PUMP 走 5K 接口等本提案**不接入**的情况）→ Mitigation：`slim_component` 在解析层加 try/except，字段缺失时把节点 `endpoint_series` 置 `None`；`get_trend_data` 收到 `None` 时走 8k 兜底（与现有 7 个生产 skill 行为一致）。如该机器实际是 5K/7K 设备，8k 接口可能返回空 → 触发标准的 empty-trend → fallback demo + `data_notes` 流程，报告不会崩
- **[Risk R7] features-tool 镜像重建** → 本提案需要重建 `deer-flow-sandbox-features-tool:latest` 并替换 docker registry / 本地 tag。Mitigation：CI 自动构建后推到内网 registry；运维侧手册更新文档；旧镜像继续可用但会缺新字段 → graceful fallback
- **[Risk R8] 2k 中文 `name` 漏映射** → 实测样本只覆盖 `"速度有效值"` / `"加速度峰值"`，生产 2k 测点可能出现更多中文 feature 名（如 `"包络谱峰值"`、`"裕度"` 等）。Mitigation：`parse_trend_response` 对未知 name 走原样透传 + debug log；上层 `_KPI_FEATURE_MAP` 找不到对应 ASCII key 即触发标准的 unmappable-KPI → fallback demo 流程，报告不会崩；运维侧定期 grep `2k name not mapped` 日志补齐
- **[Risk R9] 2k B/C/D 阈值与 8k h_alarm 语义不一致** → 8k 用 `h_alarm` / `hh_alarm`（两级），2k 用 BValue/CValue/DValue（三级 alert/alarm/danger）。Mitigation：`_aggregate_trend_to_kpi` 内部按 endpoint_series 分支选择阈值字段；`alarm_count` 统一对应 C 级越限（与 8k 的 `h_alarm` 在 alarm 一级对齐），D 级（danger）单独计入 `danger_count` 字段（如 KPI 需要）；阈值字段缺失时直接跳过该测点的 alarm 派生 + `data_notes` 提示

## Migration Plan

阶段一（本次提案合并，**默认行为不变**）：

1. 合并代码后所有部署仍走 demo（`DEER_FLOW_DATA_PROVIDER` 默认未设）
2. `make test` + `tests/test_builtin_report_templates.py` 全绿
3. 文档更新

阶段二（运维灰度，分租户）：

1. 测试租户 Gateway env 加 `DEER_FLOW_DATA_PROVIDER=ins`，先看日报
2. 7 天观察 telemetry 中 fallback 率（< 5% 视为合格），关注 `data_notes` 中的报错分类
3. 灰度 OK → 推到生产租户，同时启用周报、月报

回滚：

- L0：移除 Gateway 的 `DEER_FLOW_DATA_PROVIDER` env → 立即全量回到 demo，无需重启
- L1：保留开关但 InS 临时故障 → 自动 fallback，无需操作
- L2：`git revert` → 撤掉 Provider 注册与横幅，回到本变更前的纯 demo

## Open Questions

- **[O1 — RESOLVED] `slim_component` 中 `endpoint_series` 的机器层 `type` 取值**：已通过 InS 服务端 `MachineType` Java 枚举确认权威映射（`1=MAC→8K`、`4=PUMP→2K`、`6=PIPELINE→6K`、`9=RC→9K`、`16=VALVE→7K`）。本提案接入 1/4/6/9 四类，其它 type 走 8K 兜底。`factory_id` 经实测确认**不在** `getComponentByMachineIds` 响应中，本提案保持 `factory_id=None` 默认 + 可选 `INS_FACTORY_ID` env 的设计，无需进一步抓样。
- **D6 映射的关键字识别精度**：是否需要后续接 `ins.client.slim_component` 的 `unitType` + `name` 双因子识别？暂不做，看灰度反馈
- **多租户 InS 凭据**：当前 `INS_USERNAME` / `INS_PASSWORD` 是平台级的；若不同租户对应不同 InS 账号，需要 `data_runner` 注入租户级 InS 凭据。本次假设单一凭据，多租户放后续 spec
- **PDF 横幅样式**：`weasyprint` 渲染 `>` blockquote 的颜色是否需要自定义 CSS？跟随 markdown 默认即可，非阻塞
