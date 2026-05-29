# CRM-Agent 销售易集成 — 实施完成总结

## 已完成的实现

### Phase 1: 基础层 ✅

**新增文件**：
1. `backend/packages/harness/deerflow/integrations/models/xsy.py` — 5 个 canonical models (OutboundDetail, ServiceEventDetail, OutboundStatistics, ServiceEventStatistics, ServiceEventAnomaly)
2. `backend/packages/harness/deerflow/integrations/adapters/xsy/token_manager.py` — OAuth2 令牌管理器（自动刷新、线程安全）
3. `backend/packages/harness/deerflow/integrations/adapters/xsy/sql_builder.py` — SQL 查询构造器（字段映射、时间戳转换、分页支持）
4. `backend/packages/harness/deerflow/integrations/adapters/xsy/transform.py` — 响应转换 + 统计计算 + 异常检测算法
5. `backend/packages/harness/deerflow/integrations/adapters/xsy/adapter.py` — XsyAdapter 主适配器（6 个 capability handlers）
6. `backend/packages/harness/deerflow/integrations/adapters/xsy/__init__.py` — 包导出

**修改文件**：
- `config.py` — 增加 `system_type="xsy"`, `auth_type="xsy_oauth2"`
- `models/queries.py` — 增加 `OutboundDetailQuery`, `ServiceEventQuery`
- `registry.py` — adapter_factories 增加 `"xsy": XsyAdapter`

### Phase 2: 服务+工具层 ✅

**新增文件**：
7. `backend/packages/harness/deerflow/integrations/services/xsy_service.py` — 6 个服务方法（薄委托到 CapabilityRouter）
8. `backend/packages/harness/deerflow/integrations/tools/xsy_tools.py` — 6 个工具方法（格式化为 Markdown）

**修改文件**：
- `services/__init__.py` — 导出 XsyService
- `tools/registry.py` — 注册 XsyService + XsyTools
- `tools/tool_builder.py` — 增加 6 个 Pydantic input schemas + 6 个 StructuredTools + 6 个 arg transform 函数

### Phase 3: Skill 脚本 ✅

**新增文件**（`skills/custom/crm-analyst/`）：
9. `SKILL.md` — Skill 定义 + Agent 使用指南
10. `scripts/xsy_client.py` — 共享同步 API 客户端
11. `scripts/query_outbound.py` — 出库查询脚本
12. `scripts/query_service_events.py` — 服务事件查询脚本
13. `scripts/outbound_statistics.py` — 出库统计脚本
14. `scripts/event_statistics.py` — 事件统计脚本
15. `scripts/event_anomaly.py` — 异常检测脚本
16. `scripts/crm_report.py` — 综合报告生成脚本
17. `scripts/requirements.txt` — 依赖声明
18. `report_scripts.yaml` — 报告模板 DSL 注册

---

## 配置指南

### 1. config.yaml 添加 integrations 配置

```yaml
integrations:
  enabled: true
  systems:
    xsy_prod:
      system_type: xsy
      display_name: "销售易 CRM"
      transport_type: http
      base_url: "https://api.xiaoshouyi.com"
      auth_type: xsy_oauth2
      auth_mode: static
      timeout_seconds: 30.0
      enabled: true
      capabilities:
        - outbound.query
        - outbound.statistics
        - service_event.query
        - service_event.statistics
        - service_event.anomaly
        - xsy.report
      extra_config:
        auth_url: "https://login.xiaoshouyi.com/auc/oauth2/token"
        client_id_env: "XSY_CLIENT_ID"
        client_secret_env: "XSY_CLIENT_SECRET"
        username_env: "XSY_USERNAME"
        password_env: "XSY_PASSWORD"
  routes:
    outbound.query:
      primary_system_key: xsy_prod
    outbound.statistics:
      primary_system_key: xsy_prod
    service_event.query:
      primary_system_key: xsy_prod
    service_event.statistics:
      primary_system_key: xsy_prod
    service_event.anomaly:
      primary_system_key: xsy_prod
    xsy.report:
      primary_system_key: xsy_prod
```

### 2. extensions_config.json 启用 Skill

```json
{
  "skills": {
    "crm-analyst": {
      "enabled": true,
      "tier": "foundation"
    }
  }
}
```

### 3. 环境变量

```bash
export XSY_CLIENT_ID="53414ffe95bb61b1d29017f787b07129"
export XSY_CLIENT_SECRET="45d0f8dc8518200027dcd379d823b65f"
export XSY_USERNAME="18640311626"
export XSY_PASSWORD="sgck@2020dn9ER4hF"
```

### 4. Agent 配置（可选）

如需专用 CRM Agent，创建 `agents/builtin/crm-analyst/config.yaml`：

```yaml
name: crm-analyst
display_name: "CRM 分析师"
description: "销售易 CRM 数据分析"
tool_groups:
  - bash
  - integration
skills:
  - crm-analyst
data_tools:
  - "crm.*"
```

---

## 使用方式

### 路径 B：Agent 直接调用 StructuredTools

Agent 会自动获得以下工具（当 `data_tools` 包含 `"crm.*"` 或 `"*"` 时）：

| 工具名 | 功能 |
|--------|------|
| `crm_query_outbound` | 查询出库明细 |
| `crm_get_outbound_stats` | 出库统计 |
| `crm_query_service_events` | 查询服务事件 |
| `crm_get_event_stats` | 事件统计 |
| `crm_detect_event_anomalies` | 异常检测 |
| `crm_generate_report` | 综合报告 |

### 路径 A：沙箱内执行 Skill 脚本

Agent 读取 `SKILL.md` 后，通过 bash 工具调用脚本：

```bash
# 查询出库数据
python /mnt/skills/custom/crm-analyst/scripts/query_outbound.py \
  --start-date 2026-01-01 --end-date 2026-05-29 --limit 500 \
  --output /mnt/user-data/outputs/outbound_data.json

# 统计分析
python /mnt/skills/custom/crm-analyst/scripts/outbound_statistics.py \
  --input /mnt/user-data/outputs/outbound_data.json --group-by spec_model

# 异常检测
python /mnt/skills/custom/crm-analyst/scripts/event_anomaly.py \
  --input /mnt/user-data/outputs/service_events.json --threshold 2.0

# 生成报告
python /mnt/skills/custom/crm-analyst/scripts/crm_report.py \
  --outbound-stats /mnt/user-data/outputs/outbound_stats.json \
  --event-stats /mnt/user-data/outputs/event_stats.json \
  --anomalies /mnt/user-data/outputs/anomalies.json \
  --output /mnt/user-data/outputs/crm_report.md
```

---

## 关键实现细节

### 认证

- **Token 管理器**：`XsyTokenManager` 使用 `asyncio.Lock` 保证线程安全，过期前 5 分钟自动刷新
- **凭证解析**：优先 `extra_config`，回退到环境变量
- **预留透传**：`auth_mode="user_token"` 已预留接口，未来可支持每用户独立 token

### 分页

- 基于 id 游标（销售易 ORDER BY 仅支持 id 字段）
- 自动拉取所有页（每页 100 条），直到 query.limit 或 totalSize

### 异常检测算法

1. **频率突增**：当日事件数 > 均值 + N × 标准差
2. **新事件类型**：基线期（前 70%）未出现的事件
3. **高频机组**：事件数 > 中位数 × 2

### 错误处理

- 401/403 → `IntegrationAuthError`，token 过期则刷新后重试一次
- 429 → 退避重试（最多 3 次）
- 5xx → 按 retry_policy 重试
- Token 自动脱敏（error message 中替换为 `***REDACTED***`）

---

## 文件清单

**新增（18 个）**：
- `backend/.../integrations/models/xsy.py`
- `backend/.../integrations/adapters/xsy/{__init__.py, adapter.py, token_manager.py, sql_builder.py, transform.py}`
- `backend/.../integrations/services/xsy_service.py`
- `backend/.../integrations/tools/xsy_tools.py`
- `skills/custom/crm-analyst/{SKILL.md, report_scripts.yaml}`
- `skills/custom/crm-analyst/scripts/{xsy_client.py, query_outbound.py, query_service_events.py, outbound_statistics.py, event_statistics.py, event_anomaly.py, crm_report.py, requirements.txt}`

**修改（6 个）**：
- `backend/.../integrations/config.py`
- `backend/.../integrations/registry.py`
- `backend/.../integrations/models/queries.py`
- `backend/.../integrations/services/__init__.py`
- `backend/.../integrations/tools/registry.py`
- `backend/.../integrations/tools/tool_builder.py`

---

## 验证方案

1. **单元测试**（建议后续添加）：
   - `test_xsy_token_manager.py` — 令牌生命周期
   - `test_xsy_sql_builder.py` — SQL 生成
   - `test_xsy_transform.py` — 响应转换
   - `test_xsy_adapter.py` — 适配器协议

2. **集成测试**：
   - 配置 `xsy_prod` 系统 → Agent 调用 `crm_query_outbound` → 返回销售易真实数据
   - 沙箱内执行 `query_outbound.py` → JSON 输出 → `outbound_statistics.py` → 统计结果

3. **端到端测试**：
   - 用户询问"查询最近一周的出库数据" → Agent 选择 crm-analyst skill → 执行脚本 → 返回格式化报告

---

## 后续扩展（Out of Scope）

- 用户令牌透传（auth_mode=user_token）
- 更多销售易对象（客户、合同、商机等）
- 写回操作（POST/PATCH）
- 实时事件（Webhook）
- 缓存层（Redis）
- 定时异常检测（cron）
