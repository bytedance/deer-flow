---
name: threat-intel-collector
description: Use this skill to COLLECT black/gray-industry intelligence (ByteDance/Douyin/TikTok risk) from Telegram groups, search bots (@JISOU), and Twitter/X. It crawls history, discovers brand-new Telegram groups by keyword, and adds group links to monitoring. Each acquisition automatically runs keyword→LLM filtering and writes results to the SQLite intel store (telegram_intel_filtered/raw, day-partitioned) plus JSON/CSV. Trigger when the user wants to gather/fetch/crawl new threat intel, monitor groups, or discover sources that aren't in the database yet.
---

> ## ⚠️ 本地环境路径（务必先读）
> 当前为 **本地部署（LocalSandbox，直接在宿主机执行，没有 `/mnt` 虚拟路径）**。请用下列**真实绝对路径**，不要去 `/mnt/...`、`/mnt/user-data/workspace`、`/mnt/skills` 等不存在的目录：
> - **本 skill 脚本**：`/Users/sunnymei/project/deer-flow/skills/public/threat-intel-collector/scripts/collect.py`
> - **爬虫项目根**：`/Users/sunnymei/project/deer-flow/tg-intel-crawler`（配置/库/输出都在这）
> - **情报数据库**：`/Users/sunnymei/project/deer-flow/tg-intel-crawler/output/intel.db`
> - **Python 解释器**：`/Users/sunnymei/project/deer-flow/backend/.venv/bin/python`
> - 调用示例：
>   ```bash
>   /Users/sunnymei/project/deer-flow/backend/.venv/bin/python \
>     /Users/sunnymei/project/deer-flow/skills/public/threat-intel-collector/scripts/collect.py \
>     --action crawl-twitter --days 3
>   ```
> **严禁编造/模拟数据**：报错时用上述绝对路径重试或用 `ls`/`find` 定位真实文件，绝不"模拟/还原"数据；查不到就如实报告。
> （下文 `/mnt/skills/public/...` 为通用占位，本地替换为上面的绝对路径。）

# Threat Intel Collector Skill

## Overview

采集层（collector→curator→analyst 三件套第一环）。把黑灰产原始信号从各来源拉进来，
采集时自动完成清洗(关键词→LLM)与落库。**不做分析**（交给 threat-intel-analyst），
**不治理候选池**（交给 threat-intel-curator）。

底层调用 `tg-intel-crawler` 项目的 `tg-crawler` CLI。脚本通过环境变量
`TG_INTEL_CRAWLER_HOME` 或同级 `tg-intel-crawler/` 目录定位底层项目。

## Capabilities

| 能力 | --action | 触碰 Telegram |
|---|---|---|
| 爬已配置/已加入群历史 | `crawl` | 是 |
| 搜群 bot 按关键词检索 | `crawl-bot` | 是 |
| 爬 Twitter/X | `crawl-twitter` | 否 |
| 按关键词搜全新群 | `discover` | 是 |
| 加群链接入监控 | `add-group` | 是 |

## Workflow

### Step 1: 采集已加入群的历史（最安全）

```bash
python /mnt/skills/public/threat-intel-collector/scripts/collect.py \
  --action crawl --mode history --days 3 --joined-only
```

### Step 2: 搜库里没有的新情报（自传关键词）

```bash
# 搜群 bot
python /mnt/skills/public/threat-intel-collector/scripts/collect.py \
  --action crawl-bot --keywords "抖音 买号,刷粉"

# Twitter（独立 API，不碰 Telegram，无 FloodWait 风险）
python /mnt/skills/public/threat-intel-collector/scripts/collect.py \
  --action crawl-twitter --days 3 --keywords "杀猪盘,刷单"
```

### Step 3: 发现并加入全新 Telegram 群

```bash
# 默认 list-only：只搜+列出，不加群（安全，先给用户确认）
python /mnt/skills/public/threat-intel-collector/scripts/collect.py \
  --action discover --keywords "某APP 账号"

# 用户确认后，加 --join 限流加群（30~90s/个、每天上限20）
python /mnt/skills/public/threat-intel-collector/scripts/collect.py \
  --action discover --keywords "某APP 账号" --join
```

或直接加已知群链接：

```bash
python /mnt/skills/public/threat-intel-collector/scripts/collect.py \
  --action add-group --link https://t.me/xxxxx
```

每个脚本返回 JSON：`{ok, action, returncode, stdout, stderr}`。把 stdout 里的
统计（新增情报数、风险分布、是否触发限流）讲给用户。

## Safety

- `crawl-bot` / `discover`(带 --join) 触发 Telegram ResolveUsernameRequest，有 FloodWait 风险；
  一天内不要连续大量执行；底层撞 FloodWait 会自动停止。
- `discover` 默认 list-only，加群需显式 `--join`，且走限流。
- 仅用于安全研究与风险监控等合法用途。
- **实体不脱敏**：向用户汇报采集结果时，账号/联系方式/域名/邀请码等实体一律输出**完整原始值**，不做掩码或脱敏（这是黑灰产情报溯源的固有需求）；仅在用户显式要求时才脱敏。
