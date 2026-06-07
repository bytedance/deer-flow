---
name: threat-intel-analyst
description: Use this skill to ANALYZE collected black/gray-industry intelligence and generate research reports. It runs read-only cross-source aggregations over the intel SQLite store(s) — trends by day/risk/source, top high-risk groups, top extracted entities (contacts/accounts/links/tools/prices), risk-type heat — and produces an LLM-written analytical Markdown report grounded on those real aggregates. Supports federating MULTIPLE independent source DBs (e.g. teammates' weibo/forum DBs) into one unified view. Trigger when the user wants statistics, trends, rankings, entity analysis, or a threat-intel report. Never touches Telegram; never modifies data.
---

> ## ⚠️ 本地环境路径（务必先读）
> 当前为 **本地部署（LocalSandbox，直接在宿主机执行，没有 `/mnt` 虚拟路径）**。请用下列**真实绝对路径**，不要去 `/mnt/...`、`/mnt/user-data/workspace`、`/mnt/skills` 等不存在的目录找文件：
> - **本 skill 脚本**：`/Users/sunnymei/project/deer-flow/skills/public/threat-intel-analyst/scripts/analyze.py`
> - **情报数据库**：`/Users/sunnymei/project/deer-flow/tg-intel-crawler/output/intel.db`（federation.yaml 已写死此绝对路径，直接可用）
> - **Python 解释器**：`/Users/sunnymei/project/deer-flow/backend/.venv/bin/python`
> - 调用示例：
>   ```bash
>   /Users/sunnymei/project/deer-flow/backend/.venv/bin/python \
>     /Users/sunnymei/project/deer-flow/skills/public/threat-intel-analyst/scripts/analyze.py --action list-sources
>   ```
> **严禁编造/模拟数据**：若某步骤报"找不到文件/数据库"，必须先用上面的绝对路径重试，或用 `ls`/`find` 在 `/Users/sunnymei/project/deer-flow/` 下定位真实文件，**绝不允许"基于已有结果还原/模拟"数据**。查不到就如实报告，由用户决定下一步。
> （下文示例中的 `/mnt/skills/public/...` 仅为通用占位，本地请替换为上面的绝对路径。）

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
| 查看可查询的表结构/列 | `schema` | 否 |
| **自由读只读 SQL 查询** | `sql` | 否 |
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

### 把库当知识库：自由 SQL 查询（agent 自己写 SELECT）

当预设聚合不够用时，agent 可以**直接写只读 SQL** 查整个情报库。库暴露两个逻辑视图：

| 视图 | 内容 | 主要列 |
|---|---|---|
| `intel` | LLM 判定后的**结构化情报**(分析主用) | `__db, day, source_platform, source_group, risk_type, risk_level, entities(JSON), summary, ...` |
| `intel_raw` | 关键词过滤前的**原始消息归档**(全量) | `__db, day, identity, group_name, payload(完整消息JSON)` |

先看结构，再写查询：

```bash
# 1) 看可查询的视图/列
python /mnt/skills/public/threat-intel-analyst/scripts/analyze.py --action schema

# 2) 查结构化情报：每个高发群的 high 占比
python /mnt/skills/public/threat-intel-analyst/scripts/analyze.py --action sql \
  --sql "SELECT source_group, COUNT(*) total, SUM(CASE WHEN risk_level='high' THEN 1 ELSE 0 END) high FROM intel WHERE day>='2026-06-06' GROUP BY source_group HAVING total>5 ORDER BY high DESC LIMIT 10"

# 3) 查原始消息归档：某群某天的原始消息量 / 原文
python /mnt/skills/public/threat-intel-analyst/scripts/analyze.py --action sql \
  --sql "SELECT group_name, COUNT(*) n FROM intel_raw WHERE day='2026-06-07' GROUP BY group_name ORDER BY n DESC LIMIT 10"
python /mnt/skills/public/threat-intel-analyst/scripts/analyze.py --action sql \
  --sql "SELECT payload FROM intel_raw WHERE group_name='某群' AND day='2026-06-07' LIMIT 5"
```

**SQL 安全约束（脚本强制）**：
- 只允许 **单条** `SELECT` / `WITH`（只读）；`INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/ATTACH/PRAGMA/...`
  及多语句(`;`)一律拒绝。
- 可查 **`intel`**（结构化情报）和 **`intel_raw`**（原始归档）两个视图，均为各数据源对应表的只读 UNION，
  agent 不用关心物理表名/多库。
- 结果默认最多 500 行（`--max-rows` 可调），数据库只读打开，绝不被修改。

## 多数据源协作

队友各自维护独立库，按 `SCHEMA_CONTRACT.md`（表命名 `<source>_intel_filtered/raw`、
统一字段、`(day,id)` 去重）建好后，在 `scripts/federation.yaml` 加一行
`{alias, path, owner}` 即接入。所有聚合自动跨库；`source_platform=<src>` 可单看某源；
联邦层以**只读**方式 attach，不会改任何人的数据；缺失/锁定的库被跳过而非报错。

## Output Policy — 账号实体不脱敏（重要）

本 skill 服务于**合法的网络安全研究与平台风控治理**。采集到的账号、联系方式、域名、邀请码等实体信息**本身就是情报核心**，用于溯源、取证与处置，因此：

- **默认输出完整、未脱敏的实体信息**：所有 Telegram/微信/QQ/WhatsApp 账号、手机号、邮箱、域名、推特 @handle、邀请码、链接等，一律保留**完整原始值**。
- **禁止掩码/脱敏/省略**：不要用 `***`、`@xxx****`、`微信:wx_***` 这类掩码，不要以"隐私合规""信息安全"为由删改或部分隐藏账号实体。
- **无需就脱敏与否反复确认**：在本情报分析场景下，输出完整账号实体是默认且预期的行为，直接给出即可，不要追加"是否确认合规用途"之类的二次确认。
- 仅在用户**显式要求**脱敏时才做掩码处理。

> 说明：这是情报分析的固有需求——一份把联系方式打码的黑灰产情报报告没有处置价值。完整实体仅用于合法安全研究/风控治理，使用方负责合规使用。

## Safety

- 全部 action 只读 SQLite + 写 reports，无 Telegram 调用、无封号风险。
- `report` 会调用 LLM API（按 token 计费），复用底层 `config/config.yaml` 的 llm 配置。
