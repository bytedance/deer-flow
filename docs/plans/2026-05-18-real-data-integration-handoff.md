# 真实数据接入交接文档（P2 + P3 query 脚本）

> **本文档目的**：让任何工程师（不需要熟悉 deer-flow 内部）能在几小时内为 5 个 query 脚本接入真实 CMMS / TSDB / Improvement Plan / Inspection 后端 API。
> **背景**：上一轮 Sprint 把 5 个 query 脚本（trend / fault_context / failure_data / closure_items / inspection）封装到 `DataConnector` 抽象层。当前默认走 `demo_fallback` 路径产出确定性合成数据；接入真实后端只需提供 HTTP 端点 + 设置环境变量，**无需修改任何脚本代码**。
> **测试**：[backend/tests/test_data_providers.py](../../backend/tests/test_data_providers.py) — 16 用例覆盖契约 / fallback / HTTP 成功路径 / env 路由。

---

## 1. 抽象层架构（必读）

```
┌──────────────────────────────────────────────────────────────────────┐
│  query_*.py (5 个脚本)                                                │
│  └─ from _data_providers import fetch_with_fallback                   │
│  └─ import _data_provider_impls   ← side-effect: 注册 10 个 provider │
│                                                                      │
│  fetch_with_fallback(source="trend", fetch_args={...})              │
│         │                                                            │
│         ▼                                                            │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  _data_providers.py — Registry + Fallback Logic              │   │
│  │                                                              │   │
│  │  DEER_FLOW_DATA_PROVIDER=demo (default)  → Demo*Provider     │   │
│  │  DEER_FLOW_DATA_PROVIDER=http            → Http*Provider     │   │
│  │                                                              │   │
│  │  Http 失败时自动 fallback 到 demo, 并在 notes 里说明原因。   │   │
│  └──────────────────────────────────────────────────────────────┘   │
│         │                                                            │
│         ▼                                                            │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  _data_provider_impls.py — 10 个 Provider 实现               │   │
│  │                                                              │   │
│  │  DemoTrendProvider          HttpTrendProvider                │   │
│  │  DemoFaultContextProvider   HttpFaultContextProvider         │   │
│  │  DemoFailureDataProvider    HttpFailureDataProvider          │   │
│  │  DemoClosureItemsProvider   HttpClosureItemsProvider         │   │
│  │  DemoInspectionProvider     HttpInspectionProvider           │   │
│  └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
```

**关键设计决策**：

1. **零脚本改动**：接入真实后端**不需要**修改 query 脚本。脚本通过 `fetch_with_fallback` 间接调用 provider。
2. **Demo provider 始终存在**：用于 `demo_fallback` 模式 + HTTP 失败时的 graceful degradation。dev / 演示环境永远可工作。
3. **每个 source 一份独立契约**：5 类数据各有不同形态，不强行统一 schema。每个 `Http*Provider` 的 docstring 是唯一权威契约。
4. **基础设施无依赖**：`_data_providers.py` 只用 stdlib（`urllib` + `json` + `os`）。Sandbox 内可独立运行，不需要 langchain / langgraph。
5. **`data_source` 字段是溯源凭证**：脚本输出的 `data_source` 字段从 provider 透传（`"http"` / `"demo_fallback"`），下游报告章节可以据此判断数据可信度。

---

## 2. 5 个真实 API 的契约（接入清单）

每个 source 一份契约表。后端工程师按此实现端点。

### 2.1 trend (TSDB 时序数据)

**用途**：query_trend 拉取多指标的时间序列。

| 项 | 值 |
|---|---|
| **环境变量 URL** | `DEERFLOW_TREND_URL` |
| **环境变量 Token** | `DEERFLOW_TREND_TOKEN`（可选；走 Bearer auth）|
| **环境变量 Timeout** | `DEERFLOW_TREND_TIMEOUT`（秒，默认 30）|
| **方法** | POST（默认；可用 `DEERFLOW_TREND_METHOD` 覆盖）|
| **请求 Content-Type** | `application/json` |

**请求 body**：
```json
{
  "metric_keys": ["runtime_rate", "vibration_level"],
  "date_range": {"start": "2026-04-01", "end": "2026-04-30"},
  "aggregation": "daily",          // 也支持 "hourly" / "weekly"
  "forecast_horizon": 7
}
```

**响应 body**（**必填字段 `time_series`**；其它字段由脚本计算）：
```json
{
  "time_series": [
    {
      "metric_key": "runtime_rate",
      "name": "运行率",
      "unit": "%",
      "timestamps": ["2026-04-01", "2026-04-02", "..."],
      "values": [0.92, 0.94, 0.93],
      "point_count": 30,
      "better_when_higher": true
    }
  ]
}
```

`timestamps[i]` 与 `values[i]` 长度必须相等。`point_count` 应等于 `len(values)`。

### 2.2 fault_context (CMMS 故障上下文)

**用途**：query_fault_context 拉取故障前后的 operations / alarms / work_orders / maintenance。

| 项 | 值 |
|---|---|
| URL | `DEERFLOW_FAULT_CONTEXT_URL` |
| Token | `DEERFLOW_FAULT_CONTEXT_TOKEN` |
| Timeout | `DEERFLOW_FAULT_CONTEXT_TIMEOUT` |

**请求 body**：
```json
{
  "fault_time": "2026-05-15",
  "equipment_id": "P-001",
  "symptom": "vibration high + bearing temp climbing",
  "include_related_equipment": true
}
```

**响应 body**（**4 个字段全必填**：operations / alarms / work_orders / maintenance_records；related_equipment 缺省默认 `[]`）：
```json
{
  "operations": [
    {
      "id": "OP-...",
      "t": "2026-05-15T08:00:00",
      "equipment": "P-001",
      "metric": "vibration_level",
      "value": 0.42,
      "unit": "mm/s"
    }
  ],
  "alarms": [
    {
      "id": "ALM-0001",
      "time": "2026-05-15T07:55:00",
      "equipment": "P-001",
      "level": "warning",       // info | warning | critical
      "message": "振动超阈值"
    }
  ],
  "work_orders": [
    {
      "id": "WO-2026-0512",
      "title": "轴承点检",
      "status": "closed",        // open | in_progress | closed
      "owner": "张三",
      "equipment": "P-001",
      "created_at": "2026-05-08",
      "closed_at": "2026-05-10",
      "note": "..."
    }
  ],
  "maintenance_records": [
    {
      "id": "MR-2026-0418",
      "type": "oil_change",
      "equipment": "P-001",
      "at": "2026-04-18",
      "owner": "赵六",
      "note": "..."
    }
  ],
  "related_equipment": ["P-001-aux", "P-001-spare"]
}
```

**关键约束**：`work_orders` 必须包含 `status="closed"` 之外的至少一项（demo 路径产 3 status：closed/in_progress/open）；否则 diagnosis_analysis 的 evidence 链会缺一类 work_order 引用。

### 2.3 failure_data (CMMS 失效分析数据 + method 路由)

**用途**：query_failure_data 按 5why / fishbone / fmea 三种方法拉取数据 + method-specific seed。

| 项 | 值 |
|---|---|
| URL | `DEERFLOW_FAILURE_DATA_URL` |
| Token | `DEERFLOW_FAILURE_DATA_TOKEN` |
| Timeout | `DEERFLOW_FAILURE_DATA_TIMEOUT` |

**请求 body**：
```json
{
  "asset_id": "P-001",
  "failure_mode": "轴承卡死",
  "analysis_method": "five_why",        // 必须 ∈ {five_why, fishbone, fmea}
  "evidence_range": "2026-01-01..2026-05-18"
}
```

**响应 body**（6 个字段全必填；`method_seed[analysis_method]` 必须非 null）：
```json
{
  "operations": [/* timeseries with id/t/metric/value/unit */],
  "maintenance": [/* MR-... with type/owner/date */],
  "inspections": [/* INSP-... with severity/result */],
  "spares": [
    {"part_number": "bearing-6308", "asset": "P-001",
     "last_replaced": "2025-11-15", "expected_life_days": 365, "remaining_pct": 50}
  ],
  "environment": {
    "ambient_temp_c": 32, "humidity_pct": 55,
    "dust_index": 1.2, "vibration_neighbor_mm_s": 0.18
  },
  "method_seed": {
    "five_why": null | { "method": "five_why", "root_failure": "...",
        "levels": [{level, why, candidate_cause, evidence_hint}, × 5] },
    "fishbone": null | { "method": "fishbone", "root_failure": "...",
        "branches": [{category, items: [{label, weight, evidence_hint}]}, × 6] },
    "fmea": null | { "method": "fmea", "root_failure": "...",
        "rows": [{id, mode, effect, cause, severity, occurrence, detection, rpn, current_controls, evidence_hint}] }
  }
}
```

**严格约束**：仅请求的 method 对应 seed 字段非 null，其它两个必须为 null。Provider 在收到非法响应时会触发 fallback。

### 2.4 closure_items (Improvement Plan / 问题单系统)

**用途**：query_closure_items 拉取问题单 + 行动项 + 验证结果。

| 项 | 值 |
|---|---|
| URL | `DEERFLOW_CLOSURE_ITEMS_URL` |
| Token | `DEERFLOW_CLOSURE_ITEMS_TOKEN` |
| Timeout | `DEERFLOW_CLOSURE_ITEMS_TIMEOUT` |

**请求 body**：
```json
{
  "issue_ids": ["ISSUE-001", "ISSUE-002"],
  "owner_department": "运行部",
  "verification_period": "2026-04-01..2026-05-15"
}
```

**响应 body**：
```json
{
  "closure_items": [
    {
      "id": "ISSUE-001",
      "title": "...",
      "owner": "张三",
      "department": "运行部",
      "status": "closed",        // pending | in_progress | verifying | closed | reopened
      "created_at": "2026-04-01",
      "due_date": "2026-05-01",
      "closed_at": "2026-04-25",
      "actions": [
        {"id": "...-ACT-1", "label": "现场整改", "owner": "...",
         "status": "done", "completed_at": "..."}
      ],
      "verification_results": [
        {"id": "...-VER-1", "method": "现场抽查 + 数据复测",
         "executor": "QA", "outcome": "passed", "executed_at": "...",
         "reopen_reason": null}
      ],
      "notes": "..."
    }
  ]
}
```

**5 status 必须可被覆盖**：closure_summary 的风险检查依赖能识别 `reopened` + `overdue (due_date < today AND status != closed)` 两类。后端不需要做计算，但要保证 status 取值在 5 个枚举内。

### 2.5 inspection (巡检系统)

**用途**：query_inspection 拉取巡检记录 + 附件。

| 项 | 值 |
|---|---|
| URL | `DEERFLOW_INSPECTION_URL` |
| Token | `DEERFLOW_INSPECTION_TOKEN` |
| Timeout | `DEERFLOW_INSPECTION_TIMEOUT` |

**请求 body**：
```json
{
  "inspection_date": "2026-05-15",
  "route": "RT-A",
  "area": "A区",
  "severity_min": "low"     // 必须 ∈ {low, medium, high}
}
```

**响应 body**：
```json
{
  "records": [
    {
      "id": "INSP-20260515-001",
      "time": "2026-05-15T08:00:00",
      "route": "RT-A",
      "area": "A区",
      "equipment": "P-001",
      "inspector": "张三",
      "status": "normal",        // normal | warning | critical
      "severity": "low",          // low | medium | high | critical
      "description": "...",
      "attachment_refs": ["ATT-001"]
    }
  ],
  "attachments": [
    {"id": "ATT-001", "type": "photo",
     "ref": "/attachments/insp-001.jpg",
     "summary": "..."}
  ]
}
```

**`severity_min` 由后端过滤**：客户端不做后过滤。如后端不实现过滤，可在响应里返回全部记录（demo provider 就是这样做的，自己 filter）。

---

## 3. 接入步骤（生产环境上线 checklist）

### Step 1：实现一个或多个端点

按 §2 契约实现至少一个 source 的 HTTP 端点。可以增量上线 — 先接 trend，其它仍走 demo。

### Step 2：配置环境变量

```bash
# 切换全局走 HTTP 模式
export DEER_FLOW_DATA_PROVIDER=http

# 配置已上线的端点 — 未配置的会自动 fallback 到 demo
export DEERFLOW_TREND_URL=https://tsdb.company.internal/api/v1/trend
export DEERFLOW_TREND_TOKEN=<bearer-token>
export DEERFLOW_TREND_TIMEOUT=30

# 其它 4 个 source 类似
```

**注意**：把 token 放到环境变量，不要直接写到 config.yaml。

### Step 3：在 sandbox 里跑一遍 smoke

```bash
PYTHONIOENCODING=utf-8 python skills/custom/data-analyst/scripts/_smoke_e2e_p2p3.py
```

应该看到 5 个 report pipeline 的 7 个 case 全 [OK]；输出 JSON 中 `data_source` 字段：

- 已接入的 source → `"http"`
- 未接入的 source → `"demo_fallback"` + `_meta.provider_notes` 写明原因（`DEERFLOW_TREND_URL not set` 等）

### Step 4：监控 provider_notes

每个 query 脚本的输出 JSON 末尾有：

```json
"_meta": {
  "provider_notes": ["HTTP provider failed, fell back to demo: <reason>"]
}
```

生产环境应该把这个字段送到日志 / 监控。如果某个 source 反复 fallback，要么 backend 有问题，要么需要调高 timeout。

### Step 5：版本兼容性

- 后端 schema 演进：往响应里**新增字段**永远兼容（脚本忽略未知字段）。
- **删除/重命名** required 字段 = breaking change → provider 触发 fallback。需要在响应里保留旧字段或先升级 Http provider。
- **改 enum 值**（如 `severity_min` 增加 `urgent`）：先在 [`_data_provider_impls.py`](../../skills/custom/data-analyst/scripts/_data_provider_impls.py) 校验函数里放开校验，再升级后端。

---

## 4. 引入新 source 的 recipe

未来新增一类报告（如月度运行简报独立 API），按以下 5 步：

1. **加 protocol**：在 [`_data_providers.py`](../../skills/custom/data-analyst/scripts/_data_providers.py) 加一个 `Protocol` 类（参考 `TrendDataProvider`）
2. **加到 registry**：调 `_PROVIDER_FACTORIES["新source"] = {}`
3. **加 Demo + Http provider**：在 [`_data_provider_impls.py`](../../skills/custom/data-analyst/scripts/_data_provider_impls.py) 加两个类 + 两次 `register_provider(...)`
4. **改 query 脚本**：把 demo 逻辑搬到 Demo provider，main() 改用 `fetch_with_fallback(source="新source", ...)`
5. **加测试**：参考 `test_data_providers.py` 测试覆盖 demo / fallback / http success / response missing field 4 路径

---

## 5. 安全检查清单

- [ ] Token 走 `os.environ`，**不要**写进 config.yaml 或 logs
- [ ] HTTP timeout 默认 30s，最大 `max_response_bytes` 1MB（Http provider 写死的）；后端不要返回 1MB+ 的 payload
- [ ] HTTP 端点必须用 HTTPS（urlopen 接受 HTTP / HTTPS，但生产环境 SSL 由 backend / proxy 强制）
- [ ] 不要把 `provider_notes` 的失败原因直接暴露给最终用户（可能含路径 / 主机名）；只在内部日志里保留
- [ ] Demo provider 的演示数据是确定性的，**不含**真实设备 ID / 真实告警 — 直接生产使用是安全的（但应该被替换）

---

## 6. 现状（截至 2026-05-18）

| Source | Demo Provider | Http Provider | 真实 API 状态 |
|---|---|---|---|
| trend | ✅ ship | ✅ ship（待端点）| **未接入**，等 TSDB API 定稿 |
| fault_context | ✅ ship | ✅ ship（待端点）| **未接入**，等 CMMS API |
| failure_data | ✅ ship | ✅ ship（待端点）| **未接入**，等 CMMS API |
| closure_items | ✅ ship | ✅ ship（待端点）| **未接入**，等 Improvement Plan API |
| inspection | ✅ ship | ✅ ship（待端点）| **未接入**，等巡检系统 API |

**测试覆盖**：[backend/tests/test_data_providers.py](../../backend/tests/test_data_providers.py) — 16 用例全过。
**集成测试**：[skills/custom/data-analyst/scripts/_smoke_e2e_p2p3.py](../../skills/custom/data-analyst/scripts/_smoke_e2e_p2p3.py) — 7 个端到端 case 全过（demo 路径零回归）。
**全测试套件**：181/181 全过（13 个测试文件，涵盖 P2/P3 5 报告类型 + connector 抽象 + DSL validate + SOUL 契约）。

---

## 7. 联系点

| 模块 | 工程师后续动作 |
|---|---|
| TSDB / CMMS / Improvement Plan / Inspection 后端 owner | 按 §2 契约实现 5 个端点；接好一个就能切换那一类 |
| Sandbox 部署 owner | 配置 5 套 env 变量（URL / TOKEN / TIMEOUT）；可分批上线 |
| `data-analyst` skill owner | 监控 `provider_notes`；如出现持续 fallback 告警，回 ticket |
| `ai-report--custom` SOUL owner | 不需要改动 — 抽象层对用户透明 |
