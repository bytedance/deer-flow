---
name: threat-intel-analyst
description: Use this skill to ANALYZE collected black/gray-industry intelligence and generate research reports. It runs read-only cross-source aggregations over the intel SQLite store(s) — trends by day/risk/source, top high-risk groups, top extracted entities (contacts/accounts/links/tools/prices), risk-type heat — and produces an LLM-written analytical Markdown report grounded on those real aggregates. Supports federating MULTIPLE independent source DBs (e.g. teammates' weibo/forum DBs) into one unified view. Trigger when the user wants statistics, trends, rankings, entity analysis, or a threat-intel report. Never touches Telegram; never modifies data.
---

# Threat Intel Analyst Skill

## Overview

分析层（三件套最终环）。对 `tg-intel-crawler/output/intel.db`（collector/curator 落的库）
以及队友的其它数据源库做**只读**分析与研判。**不采集、不改库、不触碰 Telegram**，零封号风险。

```
多个独立 SQLite 库(各数据源各一个)
  → IntelFederation 只读 UNION 成统一视图
  → SQL 聚合(趋势/Top群/实体/风险热度)   ← 确定性事实
  → LLM 研判(基于聚合事实)              ← 洞察/趋势/处置建议
  → Markdown 报告(output/reports/)
```

## Setup

- 设环境变量 `TG_INTEL_CRAWLER_HOME` 指向 `tg-intel-crawler` 项目（用于定位库、LLM 配置、报告输出）。
- `scripts/federation.yaml` 注册数据源；`path: AUTO` 会自动解析为
  `$TG_INTEL_CRAWLER_HOME/output/intel.db`。队友的库按 `SCHEMA_CONTRACT.md` 建好后加一行注册即可。

## Capabilities

| 能力 | --action | LLM |
|---|---|---|
| 列出已注册数据源 | `list-sources` | 否 |
| 按天/风险/来源查记录 | `query` | 否 |
| 量级趋势 | `trends` | 否 |
| Top 风险来源群 | `top-groups` | 否 |
| 聚合抽取的实体 | `top-entities` | 否 |
| 风险类型热度 | `keyword-heat` | 否 |
| LLM 研判 Markdown 报告 | `report` | 是 |

聚合类支持范围过滤：`--day-from` / `--day-to` / `--source-platform`（telegram/bot/twitter/weibo/...）。

## Workflow

### Step 1: 看有哪些数据源在线

```bash
python /mnt/skills/public/threat-intel-analyst/scripts/analyze.py --action list-sources
```

### Step 2: 跨源统计分析

```bash
# 趋势（结果含 by_db / by_platform，跨源自动聚合）
python /mnt/skills/public/threat-intel-analyst/scripts/analyze.py --action trends --day-from 2026-06-01

# high 风险高发群
python /mnt/skills/public/threat-intel-analyst/scripts/analyze.py --action top-groups --limit 10

# 高频联系方式/账号/工具/价格
python /mnt/skills/public/threat-intel-analyst/scripts/analyze.py --action top-entities

# 风险类型热度
python /mnt/skills/public/threat-intel-analyst/scripts/analyze.py --action keyword-heat

# 只看某一源
python /mnt/skills/public/threat-intel-analyst/scripts/analyze.py --action trends --source-platform weibo
```

### Step 3: 生成 LLM 研判报告

```bash
python /mnt/skills/public/threat-intel-analyst/scripts/analyze.py --action report --day-from 2026-06-01
```

报告基于真实 SQL 聚合（不编数据），含风险概览/重点群/实体线索/趋势研判/处置建议，
落 `output/reports/intel_report_<scope>_<时间戳>.md`，并在 stdout 输出全文。

## 多数据源协作

队友各自维护独立库，按 `SCHEMA_CONTRACT.md`（表命名 `<source>_intel_filtered/raw`、
统一字段、`(day,id)` 去重）建好后，在 `scripts/federation.yaml` 加一行
`{alias, path, owner}` 即接入。所有聚合自动跨库；`source_platform=<src>` 可单看某源；
联邦层以**只读**方式 attach，不会改任何人的数据；缺失/锁定的库被跳过而非报错。

## Safety

- 全部 action 只读 SQLite + 写 reports，无 Telegram 调用、无封号风险。
- `report` 会调用 LLM API（按 token 计费），复用底层 `config/config.yaml` 的 llm 配置。
