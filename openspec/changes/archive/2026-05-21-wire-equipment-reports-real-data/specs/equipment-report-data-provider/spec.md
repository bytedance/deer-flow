## ADDED Requirements

### Requirement: InS endpoint routing by per-point series

`InsApiClient.get_trend_data(...)` SHALL route requests to one of four parallel InS trend endpoints based on a new keyword argument `endpoint_series` (`"2k" | "6k" | "8k" | "9k"`, default `"8k"` for backward compatibility) and SHALL accept an OPTIONAL `factory_id` keyword argument (default `None`). The `slim_component(...)` helper SHALL augment each emitted **point** node (not machine node) with a new field `endpoint_series` whose value is resolved by the following priority:

1. **Point-level `positionType` mapping** (values are authoritative — sourced from the InS server-side `PointPositionType` Java enum):
   - `positionType in {22..30}` → `"2k"` — legacy multi-feature vibration / acceleration / 过程量 points
     - 22=STA (W203过程量)、23=VIB (W203振动，confirmed on real sample, posName "泵前轴承_A")、24=OTHER_VIB (第三方振动)、25=STA_GENERAL (第三方过程量)、26=M_VIB (W205主轴振动)、27=S_VIB (W205辅轴振动)、28=STA_W205 (W205过程量)、29=REV_SPEED (第三方转速)、30=MAGNETIC_FLUX (磁通量)
   - `positionType in {61..64}` → `"6k"` — static-equipment corrosion monitoring (wall thickness / corrosion rate / thinning rate / process temperature)
     - 61=STA (过程量)、62=TH (在线测厚, confirmed on P-203A 出口_TH probe)、63=P (腐蚀探针)、64=OTHER_TH (离线检测)
   - `positionType in {81..83}` → `"8k"` — rotating machinery (default)
     - 81=KEY (键相 / 转速参考)、82=STA (过程量)、83=VIB (振动)
     - 8K STA(82) sub-type identification by `posName` keyword: "轴承" → bearing_temp、"阀" → valve_temp、"流量" → flow_rate、"出口压力" → outlet_pressure
   - `positionType in {91..99}` → `"9k"` — 往复机组 (high-end rotating machinery, density=high required)
     - 91=JSZD (机身振动)、92=SZT (十字头振动)、93=PBX (活塞杆偏摆X)、94=PBY (活塞杆沉降/偏摆Y)、95=GTZD (缸头振动)、96=GCYL (盖侧压力)、97=KEY (键相)、98=STA (过程量, sub-types added on demand as samples arrive)、99=ZCYL (轴侧压力)
2. **Machine-level `type` fallback** (when point has no `positionType` or `positionType` value falls outside the known ranges above) — values come from the InS server-side `MachineType` Java enum and are authoritative:
   - `type=1` (MAC, 旋转机组) → `"8k"`
   - `type=4` (PUMP, 机泵) → `"2k"` (confirmed P-3101A 进料泵)
   - `type=6` (PIPELINE, 静设备 管线/容器) → `"6k"`
   - `type=9` (RC, 往复机组) → `"9k"` (confirmed C1601 循环气压缩机)
   - Other `type` values (including `type=16` VALVE 疏水阀 → 7K and PUMP variants routed to 5K on the InS server) are **out of scope** for this proposal and fall through to step 3 (8k catch-all)
3. **Ultimate fallback**: if neither rule resolves, `endpoint_series="8k"` (since all seven existing production skills work against 8k for diverse equipment types).

`factory_id` MUST NOT be passed as a query parameter when its value is `None`. When the env `INS_FACTORY_ID` is set, `_ins_provider` SHALL pass that value as `factory_id` for every `get_trend_data` call; otherwise it MUST omit the parameter.

`_ins_provider` SHALL bucket trend fetches by `(component_id, endpoint_series)` — the same machine may have both 6k corrosion points and 8k vibration points, requiring TWO `get_trend_data` calls against different endpoints for the same machine.

Path map:

- `2k` → `/ins-os-view/data/getTrendDataHis`
- `6k` → `/ins-os-view/sg6kData/getTrendDataHis`
- `8k` → `/ins-os-view/sg8kData/getTrendDataHis` (default for backward compatibility)
- `9k` → `/ins-os-view/sg9kData/getTrendDataHis`

Query-parameter rules:

- All four endpoints take `gpids`, `startTime`, `endTime`
- `2k` / `6k` / `8k` take `density=1` (integer)
- `9k` additionally takes `density=high`, `includeFilter=history`, `typeList=<comma-joined features>`
- `factoryId` is appended only when `factory_id is not None`

#### Scenario: 6k corrosion point dispatched to sg6k path

- **WHEN** `slim_component` emits a point with `positionType=62` (e.g. P-203A 出口_TH) and `_ins_provider` calls `get_trend_data(component_id="2307110711473110001", ..., endpoint_series="6k")`
- **THEN** the HTTP request is made to `/ins-os-view/sg6kData/getTrendDataHis` with query string containing `gpids=2307110711473110001`, `density=1`, and NO `factoryId` parameter (since `factory_id=None`)

#### Scenario: 9k rotating machine dispatches with extra params

- **WHEN** `endpoint_series="9k"`, `features=["speed", "rms"]`, no `factory_id`
- **THEN** the request is made to `/ins-os-view/sg9kData/getTrendDataHis` with `density=high`, `includeFilter=history`, `typeList=speed,rms`, and NO `factoryId`

#### Scenario: 8k remains the default for existing callers

- **WHEN** an existing caller (e.g. `ins-get-trend-data` skill) invokes `get_trend_data(component_id, start_ms, end_ms, features)` without passing `endpoint_series` / `factory_id`
- **THEN** the request is made to `/ins-os-view/sg8kData/getTrendDataHis` exactly as before this change — no `factoryId` is added

#### Scenario: Same machine routes to both 6k and 8k

- **WHEN** a machine has two points — one with `positionType=62` (corrosion) and one with `positionType=83` (vibration)
- **THEN** `_ins_provider` issues TWO `get_trend_data` calls for the same machine: one to `/ins-os-view/sg6kData/...` for the corrosion point, one to `/ins-os-view/sg8kData/...` for the vibration point

#### Scenario: positionType drives point-level series

- **WHEN** the raw `getComponentByMachineIds` response returns a point with `positionType=62`
- **THEN** `slim_component` emits that point with `endpoint_series="6k"`

#### Scenario: 2k STA process-variable point routes to 2k

- **WHEN** the raw response returns a point with `positionType=22` (W203过程量, e.g. a pump bearing temperature on a 2K-routed PUMP)
- **THEN** `slim_component` emits that point with `endpoint_series="2k"`

#### Scenario: 9k positionType drives point-level series

- **WHEN** the raw response returns a point with `positionType=91` (JSZD 机身振动) on an RC machine
- **THEN** `slim_component` emits that point with `endpoint_series="9k"` (point-level positionType wins over the redundant `type=9` machine-level fallback)

#### Scenario: 8k STA(82) sub-types preserved by posName keyword

- **WHEN** an 8k point has `positionType=82` and its `posName` contains the substring "轴承" (e.g. "压缩机A 1#轴承温度")
- **THEN** `_KPI_FEATURE_MAP` resolves it as the source for `bearing_temp`. The same lookup uses "阀" → `valve_temp`, "流量" → `flow_rate`, "出口压力" → `outlet_pressure`

#### Scenario: Machine-type fallback when positionType absent

- **WHEN** a point has no `positionType` field and its parent machine has `type=4` (PUMP)
- **THEN** `slim_component` emits that point with `endpoint_series="2k"` (per InS `MachineType` Java enum: PUMP → 2K)

#### Scenario: Machine-type fallback covers MAC / PIPELINE / RC

- **WHEN** a point has no `positionType` and its machine `type` is one of `{1, 6, 9}`
- **THEN** `slim_component` emits respectively `endpoint_series="8k"` (MAC), `"6k"` (PIPELINE), `"9k"` (RC)

#### Scenario: Out-of-scope machine types fall through to 8k

- **WHEN** a point has no `positionType` and its machine `type` is `16` (VALVE 疏水阀, mapped server-side to 7K) or any other value not in `{1, 4, 6, 9}` (e.g. PUMP routed to 5K)
- **THEN** `slim_component` emits `endpoint_series="8k"` (8k catch-all). The 5K / 7K InS endpoints are not in scope for this proposal; the resulting trend fetch may return empty rows, in which case `_ins_provider` raises `HttpProviderError("InS trend_data empty for ...")` and `fetch_with_fallback` switches to demo

#### Scenario: 8k ultimate fallback for unrecognized configurations

- **WHEN** a point has no `positionType` and its machine `type` is not in the known mapping
- **THEN** `slim_component` emits `endpoint_series="8k"` for that point; `_ins_provider` proceeds with the 8k endpoint and the report is still generated with `data_source="ins"` (no fallback to demo)

#### Scenario: INS_FACTORY_ID env passes through

- **WHEN** env `INS_FACTORY_ID=119742594824536064` is set
- **THEN** every `get_trend_data` call issued by `_ins_provider` includes `factoryId=119742594824536064` in the query string

### Requirement: 2k / 6k nested response parsing

`InsApiClient.get_trend_data(...)` SHALL post-process the raw response through a new module-level helper `parse_trend_response(rows, series)` that normalizes **both** 2k and 6k nested `value` arrays into the flat shape used by 8k / 9k responses. The helper MUST be exported from `features-tool/ins/client.py` for reuse by other skills.

Two nested shapes are observed in production and MUST be handled distinctly:

- **6k shape** — feature identified by `key`:

  ```json
  {"datatime": 1777602477303, "value": [
    {"key": "corrosionRate", "name": "腐蚀率",   "unit": "mm/a", "value": "7.77"},
    {"key": "thinningRate",  "name": "减薄率",   "unit": "%",    "value": "0.057"},
    {"key": "thickness",     "name": "厚度",     "unit": "mm",   "value": "9.666"},
    {"key": "temperature",   "name": "温度",     "unit": "℃",    "value": ""}
  ]}
  ```

- **2k shape** — feature identified by Chinese `name` (no `key` field):

  ```json
  {"datatime": 1778635456000, "value": [
    {"unit": "mm/s", "name": "速度有效值", "value": 0.3006719648838043},
    {"unit": "m/s²", "name": "加速度峰值", "value": 1.8318922519683838}
  ]}
  ```

Behavior:

- `series in {"8k","9k"}` → return `rows` unchanged
- `series == "6k"` → for each row, transform the inner array into `{"datatime": <ms>, <key>: float or None, ...}`. Use the inner `key` field. String values pass through `float(...)` in a `try/except`; conversion failures (including `""`) become `None`.
- `series == "2k"` → for each row, transform the inner array into `{"datatime": <ms>, <normalized_key>: float or None, ...}`. Since 2k entries have no `key` field, the helper SHALL map the Chinese `name` to a stable ASCII key via a module-level constant `_TWO_K_NAME_KEY_MAP`. Minimum required entries (extend as more samples land):

  | name | normalized key |
  |---|---|
  | `"速度有效值"` | `v_rms` |
  | `"加速度峰值"` | `a_peak` |
  | `"加速度有效值"` | `a_rms` |
  | `"位移峰峰值"` | `pp_value` |
  | `"包络谱峰值"` | `envelope_peak` |
  | `"裕度"` | `margin` |
  | `"峭度"` | `kurtosis` |
  | `"脉冲指标"` | `pulse` |
  | `"波形指标"` | `wave` |

  Unknown names MUST be passed through as-is (`<name>: <value>`) AND a debug log emitted so future samples surface gaps without breaking the report.

- Non-numeric inner `value` fields MUST be coerced via `try/except float(...)`; non-list `value` rows MUST be skipped (debug log)

Upper-layer aggregation logic MUST treat `None` values as missing data points (i.e. exclude them from mean / count calculations).

#### Scenario: 6k row with all four features

- **WHEN** the raw response row is `{"datatime": 1777602477303, "value": [{"key": "corrosionRate", "value": "7.77"}, {"key": "thinningRate", "value": "0.057"}, {"key": "thickness", "value": "9.666"}, {"key": "temperature", "value": ""}]}`
- **THEN** `parse_trend_response` emits `{"datatime": 1777602477303, "corrosionRate": 7.77, "thinningRate": 0.057, "thickness": 9.666, "temperature": None}`

#### Scenario: 2k row with two features identified by name

- **WHEN** the raw response row is `{"datatime": 1778635456000, "value": [{"unit": "mm/s", "name": "速度有效值", "value": 0.3006719648838043}, {"unit": "m/s²", "name": "加速度峰值", "value": 1.8318922519683838}]}` and `series="2k"`
- **THEN** `parse_trend_response` emits `{"datatime": 1778635456000, "v_rms": 0.3006719648838043, "a_peak": 1.8318922519683838}`

#### Scenario: 2k row with unknown Chinese name passes through

- **WHEN** a 2k row contains `{"name": "未知指标", "value": 1.23}` and the name is not in `_TWO_K_NAME_KEY_MAP`
- **THEN** the emitted row contains `{"未知指标": 1.23}` and a debug log records the missing mapping; processing continues without raising

#### Scenario: 8k flat response passes through unchanged

- **WHEN** the raw response row is `{"datatime": 1777602477303, "pp_value": 0.85, "value": 30.5}` and `series="8k"`
- **THEN** `parse_trend_response` returns the row unchanged

#### Scenario: 9k flat response passes through unchanged

- **WHEN** the raw response row is `{"datatime": 1779113877336, "speed": 3590.5, "rms": 0.41}` and `series="9k"`
- **THEN** `parse_trend_response` returns the row unchanged

#### Scenario: Aggregation skips None values

- **WHEN** four `temperature` samples are `[25.0, None, 26.0, None]` from a 6k point
- **THEN** the daily mean for `process_temperature` is `25.5` (average of 2 non-None values), not `12.75` (which would naively include None as 0)

### Requirement: Provider registration for daily / weekly / monthly equipment reports

The data-analyst skill SHALL register `daily`, `weekly`, and `monthly` as named provider sources in `_data_providers._PROVIDER_FACTORIES`, each exposing both a `demo` and an `ins` mode that can be resolved through `get_provider(source, mode=...)` and routed by the `DEER_FLOW_DATA_PROVIDER` environment variable. `DEER_FLOW_DATA_PROVIDER` SHALL accept exactly two values: `"demo"` (default) and `"ins"`. Any other value MUST raise `KeyError` from `get_provider`.

#### Scenario: Demo provider is the default

- **WHEN** `DEER_FLOW_DATA_PROVIDER` is unset and `query_daily.fetch_day(...)` (or weekly / monthly equivalent) is called
- **THEN** `get_provider("daily")` (or `"weekly"` / `"monthly"`) returns the registered `Demo*Provider` instance and the resulting `ProviderResult.data_source` equals `"demo_fallback"`

#### Scenario: InS provider is selected via env

- **WHEN** `DEER_FLOW_DATA_PROVIDER=ins`
- **THEN** `get_provider(<source>)` returns the corresponding `Ins*Provider` instance, which delegates to `_ins_provider.fetch_<source>_payload(...)`

#### Scenario: Unsupported provider value raises

- **WHEN** `DEER_FLOW_DATA_PROVIDER=http` (legacy / typo) is set and `get_provider("daily")` is called
- **THEN** `get_provider` raises `KeyError("no provider registered for source='daily' mode='http'; registered=['demo', 'ins']")`

### Requirement: features-tool import isolation

The new module `skills/custom/data-analyst/scripts/_ins_provider.py` SHALL inject `os.environ["FEATURES_TOOL_ROOT"]` (default `/opt/features-tool`) into `sys.path` and attempt `from ins import InsApiClient, load_ins_settings`. Import failure MUST NOT crash the script — instead, the module-level constant `_FEATURES_TOOL_AVAILABLE` MUST be set to `False`, and any subsequent `Ins*Provider.fetch(...)` call MUST raise `HttpProviderError("features-tool not available: <reason>")` so `fetch_with_fallback` switches to the demo provider.

#### Scenario: features-tool present

- **WHEN** `/opt/features-tool/ins/__init__.py` exists and `import ins` succeeds during `_ins_provider` module load
- **THEN** `_FEATURES_TOOL_AVAILABLE` is `True`

#### Scenario: features-tool missing (local sandbox)

- **WHEN** `FEATURES_TOOL_ROOT` is unset and `/opt/features-tool` does not exist
- **THEN** `_FEATURES_TOOL_AVAILABLE` is `False`, and calling `InsDailyProvider().fetch(...)` raises `HttpProviderError` mentioning "features-tool not available"

#### Scenario: Import failure triggers fallback in script main path

- **WHEN** `DEER_FLOW_DATA_PROVIDER=ins` is set but `_FEATURES_TOOL_AVAILABLE` is `False`, and `query_daily.py` runs
- **THEN** the script writes `daily_data.json` with `data_source="demo_fallback"` and `data_notes` containing a string of the form `"HTTP provider failed, fell back to demo: features-tool not available: <reason>"`

### Requirement: InS provider invocation contract

Each `Ins{Daily,Weekly,Monthly}Provider.fetch(...)` SHALL delegate to a single async helper in `_ins_provider.py` that wraps `InsApiClient` calls inside `asyncio.run(...)`. The helper MUST:

1. Call `load_ins_settings()` once per process
2. Instantiate one `InsApiClient(settings)` per fetch call and call `await ins.close()` in `finally`
3. Call `await ins.get_components(machine_id)` for each unique machine ID present in the equipment list (cached within one fetch call)
4. Bucket the discovered points by `endpoint_series` and call `await ins.get_trend_data(component_id, start_ms, end_ms, features, endpoint_series=<series>, factory_id=<env-or-none>)` once per `(component_id, endpoint_series)` bucket
5. Aggregate point-level trend rows into the `current` / `compare` payload shape that `query_daily.build_result` (and weekly / monthly equivalents) expects — for 6k points the rows are already flattened by `parse_trend_response`, with `None` values excluded from aggregates
6. Return a `ProviderResult` with `data_source="ins"` and an empty `data_notes` list on success

#### Scenario: Single machine daily fetch

- **WHEN** `InsDailyProvider.fetch(date_str="2026-05-19", equipment_ids=["180906045526625"], kpi_keys=["vibration_level"], eq_type="rotating_machinery", compare_with="previous_day", equipment_meta={"180906045526625": {"name": "压缩机A"}})` is called and InS returns valid trend data
- **THEN** the resulting payload contains `current.kpis.vibration_level` (mean of `pp_value` across the day), `current.hourly_runtime_rate` (24 floats derived from `speed`), and `compare` block for `2026-05-18`; `data_source` is `"ins"`

#### Scenario: Mixed-endpoint single machine fetch

- **WHEN** a machine has both a 6k corrosion point (`positionType=62`) and an 8k vibration point (`positionType=83`), and `kpi_keys=["corrosion_rate", "vibration_level"]`
- **THEN** `_ins_provider` issues two `get_trend_data` calls — one to `/ins-os-view/sg6kData/...` and one to `/ins-os-view/sg8kData/...` — and the resulting payload contains both `current.kpis.corrosion_rate` and `current.kpis.vibration_level`; `data_source` is `"ins"`

#### Scenario: get_components fails for unknown device

- **WHEN** the user-selected `equipment_ids` contains an ID that returns `[]` from `get_components`
- **THEN** `_ins_provider` raises `HttpProviderError("device <id> not found in InS")` and `fetch_with_fallback` switches to demo with that note appended

#### Scenario: get_trend_data returns empty

- **WHEN** `get_trend_data` returns `[]` for the requested time window
- **THEN** `_ins_provider` raises `HttpProviderError("InS trend_data empty for <component_id> [<start>..<end>]")` and falls back to demo

#### Scenario: HTTP timeout

- **WHEN** `InsApiClient` raises `httpx.TimeoutException` or `RuntimeError` during login / data fetch
- **THEN** the exception is caught and re-raised as `HttpProviderError` so the demo provider takes over; the original message is preserved in `data_notes`

### Requirement: KPI to InS feature mapping (rotating + static corrosion)

The `_ins_provider` module SHALL maintain a constant `_KPI_FEATURE_MAP` that maps each supported daily / weekly / monthly KPI key to the InS retrieval rule needed to derive its value. Mapping MUST cover BOTH rotating-machinery KPIs (via 2k / 8k / 9k endpoints) AND static-equipment corrosion-monitoring KPIs (via the 6k endpoint).

**Rotating machinery (8k / 9k)**:

- `vibration_level` ← `pp_value` from `positionType=83` points (daily mean)
- `bearing_temp` ← `value` from `positionType=82` points containing "轴承" (daily mean)
- `valve_temp` ← `value` from `positionType=82` points containing "阀" (daily mean)
- `flow_rate` ← `value` from `positionType=82` points containing "流量" (daily mean)
- `outlet_pressure` ← `value` from `positionType=82` points containing "出口压力" (daily mean)
- `runtime_rate` ← `speed` from `positionType=81` points, computed as `count(speed>0) / count(*)`
- `alarm_count` ← `value` vs `h_alarm` / `hh_alarm` thresholds, count of exceedances per day
- `downtime_count` ← `speed` from `positionType=81`, count of `speed>0 → speed=0` transitions

**Static-equipment corrosion (6k)**:

- `corrosion_rate` ← `corrosionRate` from `positionType=62` points (daily mean of non-None values)
- `thickness_loss` ← `thickness` from `positionType=62`, computed as `first_thickness - last_thickness` over the time window (mm)
- `thinning_rate` ← `thinningRate` from `positionType=62` (daily mean of non-None values)
- `process_temperature` ← `temperature` from `positionType=62` (daily mean of non-None values; empty-string samples already converted to `None` by `parse_trend_response`)

KPIs not in the map (e.g. `output`, `energy_consumption`, `piston_ring_wear` and other InS-uncovered metrics) MUST trigger an immediate `HttpProviderError("KPI <key> has no InS mapping")` so the entire report falls back to demo — partial-source mixing is forbidden.

#### Scenario: Rotating-only KPI list succeeds

- **WHEN** the request is `kpi_keys=["vibration_level", "runtime_rate"]` and InS returns valid 8k data
- **THEN** `current.kpis` has both keys populated and the report is `data_source="ins"`

#### Scenario: Corrosion-only KPI list succeeds via 6k

- **WHEN** the request is `kpi_keys=["corrosion_rate", "thickness_loss"]` against equipment whose points have `positionType=62`
- **THEN** `_ins_provider` issues `get_trend_data(..., endpoint_series="6k")`, parses the nested response, computes `corrosion_rate` as daily mean and `thickness_loss` as first-minus-last; `data_source` is `"ins"`

#### Scenario: Mixed rotating + corrosion KPI succeeds

- **WHEN** the request is `kpi_keys=["vibration_level", "thickness_loss"]` against a machine that has both 8k and 6k points
- **THEN** the resulting payload contains real values for both KPIs from their respective endpoints; `data_source` is `"ins"`

#### Scenario: Unmappable KPI forces full fallback

- **WHEN** the request is `kpi_keys=["vibration_level", "output"]` (where `output` is not in the map)
- **THEN** the entire fetch raises `HttpProviderError("KPI 'output' has no InS mapping")`, the report falls back to demo for **all** KPIs (not just `output`), and `data_notes` contains the message

#### Scenario: alarm_count derivation uses h_alarm/hh_alarm

- **WHEN** `kpi_keys` includes `alarm_count` and `slim_component` provides `h_alarm=80.0` for a bearing temp point
- **THEN** the derivation counts trend rows whose `value` exceeds 80.0 within the day window; the result is the `alarm_count` value in `current.kpis`

#### Scenario: runtime_rate derivation uses speed > 0 ratio

- **WHEN** `kpi_keys` includes `runtime_rate` and the type=81 speed point has 1440 minute samples with 1300 having `speed > 0`
- **THEN** `current.kpis.runtime_rate == 1300/1440 == 0.9028` (rounded to 4 decimals)

#### Scenario: thickness_loss derivation uses first-minus-last

- **WHEN** `kpi_keys` includes `thickness_loss` and the 6k point returns `thickness` samples `[9.666, 9.664, 9.663, 9.660]` over the day window
- **THEN** `current.kpis.thickness_loss == 9.666 - 9.660 == 0.006` (mm)

### Requirement: Wire query scripts to fetch_with_fallback

`query_daily.py:fetch_day`, `query_weekly.py:fetch_week`, and `query_monthly.py:fetch_month` SHALL invoke `fetch_with_fallback(source=..., fetch_args=...)` rather than calling demo helpers directly. `_demo_*` functions remain as the backing implementation of the registered `Demo*Provider`. Any `HttpProviderError` raised during the InS path MUST be caught and replaced by the demo provider's result; fallback MUST NOT raise to the script's `main()` and MUST NOT emit `{"error": ...}`.

#### Scenario: Demo provider exception still bubbles

- **WHEN** the demo provider itself raises (programming bug, not an InS error)
- **THEN** the exception propagates to `main()` so it surfaces as `{"error": "<ExceptionType>: <message>"}` — fallback only catches `HttpProviderError`

#### Scenario: Compare period falls back atomically

- **WHEN** the InS fetch for the `current` period succeeds but the `compare` period (e.g. previous day) raises `HttpProviderError`
- **THEN** the entire report falls back to demo for both `current` and `compare` (no mixed-source output); `data_notes` contains the failure detail

### Requirement: data_source and data_notes fields in script output

`query_daily.py`, `query_weekly.py`, and `query_monthly.py` SHALL write two new top-level fields into their output JSON files (`daily_data.json` / `weekly_data.json` / `monthly_data.json`): `data_source` (string, exactly one of `"ins"` or `"demo_fallback"`) and `data_notes` (array of strings, possibly empty). The downstream `daily_kpi.py` / `weekly_kpi.py` / `monthly_kpi.py` transforms SHALL preserve these two fields verbatim into their respective KPI outputs.

#### Scenario: Demo path writes demo_fallback

- **WHEN** the script runs with `DEER_FLOW_DATA_PROVIDER` unset and writes the output JSON
- **THEN** the JSON contains `"data_source": "demo_fallback"` and `"data_notes": []` at the top level (not nested inside `current` or `compare`)

#### Scenario: InS success writes ins

- **WHEN** `DEER_FLOW_DATA_PROVIDER=ins` and the fetch succeeds end-to-end
- **THEN** the JSON contains `"data_source": "ins"` and `"data_notes": []`

#### Scenario: KPI transform preserves both fields

- **WHEN** `daily_kpi.py` reads `daily_data.json` with `data_source=demo_fallback` and `data_notes=["features-tool not available: ..."]`
- **THEN** the resulting `daily_kpi.json` carries the same two values at its top level alongside `kpi_summary`, `trend_chart`, etc.

### Requirement: Markdown banner reflecting data source

The `export_report.render_markdown` function SHALL emit, as the very first line of the rendered markdown body, a banner that depends on `payload["data_source"]`:

- when `data_source == "ins"`: `> ✅ 数据来源：InS 实时接入`
- when `data_source == "demo_fallback"` and `data_notes` is empty: `> ⚠️ 当前使用演示数据（fallback）。原因：未配置真实数据源（DEER_FLOW_DATA_PROVIDER 未设置为 ins）`
- when `data_source == "demo_fallback"` and `data_notes` is non-empty: `> ⚠️ 当前使用演示数据（fallback）。原因：<data_notes[0]>`

The banner MUST appear before the report title section. Both `ai-report--{daily,weekly,monthly}` SOUL paths and the corresponding builtin DSL templates SHALL rely on this rendered markdown — neither path may produce a final markdown that omits the banner. Banner injection MUST be idempotent: invoking `render_markdown` twice on the same payload SHALL NOT double-prepend the banner.

#### Scenario: Demo banner without explicit reason

- **WHEN** rendering markdown from a payload with `data_source="demo_fallback"` and `data_notes=[]`
- **THEN** the first markdown line is `> ⚠️ 当前使用演示数据（fallback）。原因：未配置真实数据源（DEER_FLOW_DATA_PROVIDER 未设置为 ins）`

#### Scenario: Demo banner with explicit fallback reason

- **WHEN** rendering markdown from a payload with `data_source="demo_fallback"` and `data_notes=["features-tool not available: ..."]`
- **THEN** the first markdown line is `> ⚠️ 当前使用演示数据（fallback）。原因：features-tool not available: ...`

#### Scenario: InS real-data banner

- **WHEN** rendering markdown from a payload with `data_source="ins"`
- **THEN** the first markdown line is `> ✅ 数据来源：InS 实时接入`

#### Scenario: PDF export inherits banner

- **WHEN** `export_report.write_report(payload, "pdf")` runs after `write_report(payload, "md")`
- **THEN** the PDF contains the same banner as the markdown — the export logic MUST NOT strip or relocate it

#### Scenario: Repeated render is idempotent

- **WHEN** `render_markdown(payload)` is called and its output is passed back into `render_markdown(...)` again (some agents do this)
- **THEN** the second call MUST NOT prepend a second banner

### Requirement: Backward-compatible default behavior

Setting neither `DEER_FLOW_DATA_PROVIDER` nor invoking InS in any way MUST keep all three scripts producing exactly the same data they produced before this change, except for the two new `data_source` / `data_notes` top-level fields and the markdown banner. Existing tests in `backend/tests/test_ai_report_daily_*.py`, `test_ai_report_weekly_*.py`, `test_ai_report_monthly_*.py`, and `test_builtin_report_templates.py` MUST continue to pass without source code changes apart from additive field assertions.

#### Scenario: Existing daily smoke test still passes

- **WHEN** `pytest backend/tests/test_ai_report_daily_query.py` runs after this change with no envs set
- **THEN** all existing assertions on `equipment_ids`, `kpi_keys`, `compare_type`, `compare_date`, `current.kpis`, `current.hourly_runtime_rate`, `alarms` still pass

#### Scenario: Builtin DSL validator still green

- **WHEN** `pytest backend/tests/test_builtin_report_templates.py` runs after the new banner section is added to `agents/builtin/report-templates/{daily,weekly,monthly}-equipment/default.yaml`
- **THEN** the validator accepts the new `markdown` section pointing at `data_source_banner` without warnings

### Requirement: Sandbox mode constraint

InS real-data path SHALL only function inside the docker sandbox provided by `deer-flow-sandbox-features-tool` image (which copies `features-tool` to `/opt/features-tool` and pre-installs its `requirements.txt`). When the sandbox is configured otherwise — `LocalSandboxProvider`, a custom image without `features-tool`, or a misconfigured `FEATURES_TOOL_ROOT` — the system SHALL silently fall back to demo and document the cause in `data_notes`.

#### Scenario: Local sandbox produces demo fallback

- **WHEN** the agent runs in `LocalSandboxProvider` mode (no `/opt/features-tool` directory) and `DEER_FLOW_DATA_PROVIDER=ins`
- **THEN** the report is generated with `data_source="demo_fallback"` and the banner reason mentions "features-tool not available"

#### Scenario: Custom sandbox image without features-tool

- **WHEN** the operator points `sandbox.image` at a base image that doesn't include `features-tool`
- **THEN** the same fallback occurs at runtime; no error is raised to the user

### Requirement: Operational documentation

Operations-facing documentation (`backend/docs/HTTP_CONNECTORS.md` and `backend/CLAUDE.md`) SHALL be updated to enumerate the single new env (`DEER_FLOW_DATA_PROVIDER`), the optional env (`INS_FACTORY_ID`), explain that InS credentials (`INS_USERNAME` / `INS_PASSWORD`) and `FEATURES_TOOL_ROOT` are reused from existing sandbox config, document the four endpoint series (2k/6k/8k/9k) and their use cases, and explicitly state the docker-sandbox-only constraint.

#### Scenario: Docs explain single switch

- **WHEN** an operator reads `backend/docs/HTTP_CONNECTORS.md` after this change
- **THEN** the docs contain a "设备日/周/月报真数据" subsection that documents `DEER_FLOW_DATA_PROVIDER=ins` as the only required env, lists `INS_FACTORY_ID` as an optional override, enumerates the four endpoint series with their use cases (2k legacy / 6k 静设备腐蚀监测 / 8k 旋转机组默认 / 9k 高端旋转机组), and states that all InS credentials are inherited from existing `sandbox.environment` config

#### Scenario: CLAUDE.md cross-reference

- **WHEN** a developer reads `backend/CLAUDE.md`
- **THEN** the "Skills System" or "Data analyst" section mentions the `data_source` field and links to `docs/HTTP_CONNECTORS.md` for the env-switch contract
