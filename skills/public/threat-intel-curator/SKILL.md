---
name: threat-intel-curator
description: Use this skill to GOVERN the discovered-groups candidate pool for black/gray-industry monitoring. It reports pool stats, verifies candidates' real Telegram entity type via get_entity (rejecting personal accounts, bots, and dead usernames so only real groups remain), and lets the LLM pick high-value candidate groups, join them (rate-limited), and crawl them. Trigger when the user wants to clean/verify the candidate pool, filter out non-group accounts, or have the model auto-select and crawl promising groups.
---

# Threat Intel Curator Skill

## Overview

候选池治理层（三件套中间环）。collector 采集时会反向发现新群、攒进候选池
(`discovered_groups.yaml`)；curator 负责把池子治理干净并转化为真正在爬的群。
底层调用 `tg-crawler` CLI（通过 `TG_INTEL_CRAWLER_HOME` 定位）。

## Capabilities

| 能力 | --action | 触碰 Telegram |
|---|---|---|
| 候选池状态统计 | `stats` | 否（本地） |
| 校验候选类型(过滤账号/机器人/无效) | `verify` | 是 |
| LLM 选群→校验→加群→爬取 | `llm-crawl` | 是 |

## Workflow

### Step 1: 看候选池状态

```bash
python /mnt/skills/public/threat-intel-curator/scripts/curate.py --action stats
```

### Step 2: 清洗候选池（过滤个人账号/机器人）

```bash
# 先 dry-run 看会判哪些为非群组
python /mnt/skills/public/threat-intel-curator/scripts/curate.py \
  --action verify --max 80 --interval 3 --dry-run

# 正式跑（个人账号/机器人/无效用户名标记 rejected）
python /mnt/skills/public/threat-intel-curator/scripts/curate.py \
  --action verify --max 80 --interval 3
```

> 候选多就多跑几轮，每轮自动挑高频候选优先校验。单轮 max ≤80、interval ≥3s（防 FloodWait）。

### Step 3: 让 LLM 选群并爬取

```bash
# 先 dry-run 看 LLM 选了哪些群（含实体类型校验，会标出非群组并跳过）
python /mnt/skills/public/threat-intel-curator/scripts/curate.py \
  --action llm-crawl --days 3 --min-confidence high --max-crawl 3 --dry-run

# 确认后正式跑
python /mnt/skills/public/threat-intel-curator/scripts/curate.py \
  --action llm-crawl --days 3 --min-confidence high --max-crawl 3
```

返回 JSON：`{ok, action, returncode, stdout, stderr}`。解读 stdout 的统计给用户。

推荐顺序：`verify` 清洗 → `llm-crawl`（先 dry-run）。

## Safety

- `verify` / `llm-crawl` 触发 Telegram ResolveUsernameRequest，有 FloodWait 风险；撞限制底层自动停止。
- `llm-crawl` 会限流加群(30~90s/个、每天上限20)，务必先 dry-run 确认选群。
- `stats` 为纯本地只读。
