---
name: crm-analyst
description: 销售易 CRM 数据分析——产品出库查询与统计、服务事件查询与异常检测、综合报告生成。当用户询问出库数据、服务事件、机组异常、CRM 报告时使用。
metadata:
  emoji: "📊"
---

# CRM Analyst Skill

本 Skill 提供销售易 CRM 数据分析能力，包括产品出库明细查询与统计、服务事件查询与异常检测、综合报告生成。

## 使用场景

当用户询问以下内容时使用本 Skill：
- 产品出库数据、出库统计、规格型号分析
- 服务事件查询、事件统计、机组事件频率
- 异常检测、频率突增、新事件类型
- CRM 综合报告

## 工作流程

### 1. 数据查询

查询产品出库明细：
```bash
python /mnt/skills/custom/crm-analyst/scripts/query_outbound.py \
  --start-date 2026-01-01 \
  --end-date 2026-05-29 \
  --spec-model "W203" \
  --limit 500
```

查询服务事件明细：
```bash
python /mnt/skills/custom/crm-analyst/scripts/query_service_events.py \
  --start-date 2026-01-01 \
  --end-date 2026-05-29 \
  --unit-name "机组A" \
  --limit 500
```

### 2. 统计分析

对出库数据进行统计分析：
```bash
python /mnt/skills/custom/crm-analyst/scripts/outbound_statistics.py \
  --input /mnt/user-data/outputs/outbound_data.json \
  --group-by spec_model
```

对服务事件进行统计分析：
```bash
python /mnt/skills/custom/crm-analyst/scripts/event_statistics.py \
  --input /mnt/user-data/outputs/service_events.json \
  --group-by device_name
```

### 3. 异常检测

检测服务事件中的异常模式：
```bash
python /mnt/skills/custom/crm-analyst/scripts/event_anomaly.py \
  --input /mnt/user-data/outputs/service_events.json \
  --threshold 2.0
```

### 4. 综合报告

生成综合分析报告：
```bash
python /mnt/skills/custom/crm-analyst/scripts/crm_report.py \
  --outbound-data /mnt/user-data/outputs/outbound_data.json \
  --event-data /mnt/user-data/outputs/service_events.json \
  --outbound-stats /mnt/user-data/outputs/outbound_stats.json \
  --event-stats /mnt/user-data/outputs/event_stats.json \
  --anomalies /mnt/user-data/outputs/anomalies.json \
  --output /mnt/user-data/outputs/crm_report.md
```

## 环境变量

脚本需要以下环境变量（由系统自动注入）：
- `XSY_CLIENT_ID` - 销售易 OAuth2 client_id
- `XSY_CLIENT_SECRET` - 销售易 OAuth2 client_secret
- `XSY_USERNAME` - 服务账号用户名
- `XSY_PASSWORD` - 服务账号密码

## 注意事项

- 所有日期格式为 `YYYY-MM-DD`
- 查询结果以 JSON 格式输出
- 统计分析和异常检测结果以 JSON 格式输出
- 综合报告以 Markdown 格式输出
- 每次查询最多返回 500 条记录（可调整 --limit 参数）
