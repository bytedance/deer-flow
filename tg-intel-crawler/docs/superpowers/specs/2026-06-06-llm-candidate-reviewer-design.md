# LLM 候选群组自动审查 (`candidates llm-review`) 设计

> 让 LLM 接管 `candidate_pool` 的初审工作：根据候选群在消息里被传播的方式，自动判断它是否属于字节系黑灰产、给出置信度，可选地把高置信度候选写入 `config.groups` 并触发限流加群。

---

## 1. 背景与动机

`tg-crawler crawl` 通过反向发现把每条消息里出现的 `t.me/...` / `@username` / `+invite_hash` 写入 `config/discovered_groups.yaml`，目前已经累积到 7000+ 条候选。现有审查流程完全是人工：

```bash
tg-crawler candidates list                # 看候选池
tg-crawler candidates approve foo bar     # 限流加群 + 写 config.groups
tg-crawler candidates reject baz          # 永久拒绝
```

候选池规模再增长，人工逐条 review 成本太高；而候选 yaml 里其实存了足够多的信号（被哪些群传播、被传播多少次、什么时候开始/最近被传播）可以让 LLM 做初审。

**目标**：在不破坏现有 `candidates approve/reject` 流程的前提下，加一条 `tg-crawler candidates llm-review` 命令，让 LLM 自动审查 pending 候选，给出置信度判决，可选地落 config 和加群。

**非目标**：
- 不取代人工最终决策权 —— LLM 永远不写 `status: rejected`，人工 reject 永远不被 LLM 推翻
- 不引入新的外部依赖（继续用 `config.llm` 里配的 OpenAI 兼容协议）
- 不依赖 `@JISOU` 等搜群 bot 反查（bot 只能搜聊天记录，无法用群链接反查群本身）

---

## 2. 决策摘要（与用户确认过的）

| 决策 | 选择 |
|---|---|
| LLM 拿什么证据判断 | 两阶段：Stage1 仅 metadata（含来源群信誉衍生字段），Stage1 advance 的进 Stage2 看来源消息原文 |
| 高置信度命中后的行为 | 分级：高 → 自动加群；中 → 仅写 `config.groups` 不加群；低 → 留 pending 仅记 verdict |
| 判决结果存哪里 | 直接扩 `discovered_groups.yaml`：每个候选加可选 `llm_verdict` 字段 |
| 与现有 approve/reject 共存规则 | LLM 只动 status=pending 的候选，永远不写 `status: rejected` |
| 命令入口形态 | 独立子命令 `tg-crawler candidates llm-review`，未来再嵌入 crawl 流程 |

---

## 3. 架构

新增模块 `tg_intel_crawler/filter/candidate_reviewer.py`，与现有 `LLMFilter` 平行（一个判消息内容，一个判候选群）。共用 `config.llm` 的 `AsyncOpenAI` 客户端配置，但独立的 system prompt / schema。

```
┌─────────────────────────────────────────────────────────────────┐
│              tg-crawler candidates llm-review                   │
│                  (main.py 新增子命令)                            │
└──────────────────┬──────────────────────────────────────────────┘
                   │ 编排
                   ▼
┌──────────────────────────────────────┐    ┌──────────────────────┐
│      CandidateReviewer (新)          │◄───│  CandidatePool       │
│  ──────────────────────              │    │  (扩 llm_verdict)    │
│  pick_candidates_to_review()         │    └──────────────────────┘
│  build_evidence(candidate)           │◄───┐
│  stage1_metadata_review(batch)       │    │
│  stage2_text_review(candidate)       │    │  RawMessageLookup (新)
│  finalize_verdict(stage1, stage2)    │    │  按 (group_name, msg_id) 反查
└──────────┬───────────────────────────┘    │  output/raw/*.json
           │                                 └──────────────────────┘
           │                                        ▲
           │ Stage1 LLM (批量, metadata-only)      │
           │ Stage2 LLM (单条, 含原文)             │
           ▼                                        │
┌──────────────────────────────────────┐    ┌──────────────────────┐
│  AsyncOpenAI(config.llm)             │    │  IntelStatsAggregator│
│  (复用 LLMFilter 的客户端配置)        │    │  从 output/filtered/ │
└──────────────────────────────────────┘    │  算来源群历史信誉    │
                                            └──────────────────────┘
```

**为什么不直接扩 `LLMFilter`**：`LLMFilter` 的 system prompt / 返回 schema 都围绕"单条黑灰产消息"，与"候选群初审"的输入输出结构都不同。强行复用会让 prompt 变成两个 prompt 的 union，难维护。新增独立类、共用底层 `AsyncOpenAI` 配置即可。

### 模块职责

| 模块 | 职责 | I/O |
|---|---|---|
| `CandidateReviewer` | 编排两阶段判决；不直接读写 yaml | 输入：candidate dicts；输出：verdict dicts |
| `CandidatePool`（改） | 新增 `pending_for_review` / `set_llm_verdict` / `apply_llm_approvals` | 仍是 yaml 唯一真理源 |
| `RawMessageLookup`（新） | 按 `(group_name, msg_id)` 在 `output/raw/*.json` 里反查原文 | 启动时建索引、内存缓存 |
| `IntelStatsAggregator`（新） | 扫 `output/filtered/intel_*.json`，按 `source_group` 聚合 high/medium intel 计数 | 启动时算一次、内存缓存 |
| `main.py` 新子命令 | 解析 flag、组装组件、打印汇总报告 | CLI |

---

## 4. 数据模型：`llm_verdict` 字段

每个候选新增可选字段（不存在表示 LLM 没看过）：

```yaml
candidates:
  douyinhao88:
    invite_hash: null
    first_seen: '2026-06-05T08:30:00+00:00'
    last_seen:  '2026-06-08T22:15:00+00:00'
    count: 7
    status: approved          # 由 --write-config 触发，从 pending 改来
    sources: [...]
    llm_verdict:
      verdict: llm_approved_high  # 闭集 (见下)
      confidence: high            # high | medium | low
      risk_type: 账号交易         # 与 LLMFilter 对齐的风险类型词表
      reason: 三条来源消息均为抖音老号交易语境，candidate 是卖家 telegram 联系方式
      reviewed_at: '2026-06-09T10:00:00+00:00'
      reviewed_count: 7           # review 时的 count，用于增量重审判断
      stage: 2                    # 1 = Stage1 终结；2 = 进了 Stage2
      model: ep-2026xxxxxx        # 留痕，方便切模型后判断要不要重跑
```

**`verdict` 闭集**：
- `llm_approved_high`：Stage2 approve + confidence=high
- `llm_approved_medium`：Stage2 approve + confidence=medium
- `llm_approved_low`：Stage2 approve + confidence=low
- `llm_rejected`：Stage1 reject 或 Stage2 reject

**重审触发条件**（任一满足）：
- 没有 `llm_verdict` 字段（从未 review 过）
- `count > reviewed_count * 2`（候选热度显著上涨）
- `now - reviewed_at > 30 天`（陈旧）
- `--force-rereview` flag 强制

**重审范围**：所有 `status == pending` 的候选都参与重审判断，**包括**之前被打过 `llm_rejected` 的（因为 status 仍然是 pending 而不是 rejected）。这是有意为之 —— LLM 之前判错了、但候选热度上涨了，应该再看一次。如果你想"永久封禁"某个候选不让 LLM 再看，正确做法是 `tg-crawler candidates reject <key>` 把 status 改成 `rejected`。

**互斥规则**：
- LLM 只读 `status == pending` 的候选；status 是 `approved` / `rejected` 的人工决定永远不被 LLM 触碰
- LLM 永远不写 `status: rejected`；最重也只是给个 `llm_rejected` verdict + 留在 pending
- `status: pending → approved` 仅在 `--write-config` 触发时发生（针对 `llm_approved_high` 和 `llm_approved_medium`）

---

## 5. 两阶段判决细节

### 5.1 Stage 1：Metadata 粗筛（便宜，批量）

**目的**：用最便宜的 token 砍掉明显无关的候选（如"今日有羊毛🦙"群里偶尔被 mention 一次的私密群）。

**输入证据**（每个候选打包成一行 JSON）：

```json
{
  "index": 0,
  "key": "douyinhao88",
  "type": "public",
  "count": 7,
  "first_seen": "2026-06-05",
  "last_seen": "2026-06-08",
  "sources": [
    {"group": "公群99", "channel": "text"},
    {"group": "抖音实名", "channel": "forward"},
    {"group": "刷粉接单", "channel": "text"}
  ],
  "source_groups_intel_score": {
    "公群99":   {"high": 12, "medium": 30, "total_msgs": 800},
    "抖音实名": {"high": 50, "medium": 80, "total_msgs": 1200},
    "刷粉接单": {"high":  8, "medium": 22, "total_msgs":  400}
  }
}
```

`source_groups_intel_score` 是新写的衍生统计：扫 `output/filtered/intel_*.json`，按 `source_group` 聚合每个群历史上产出过多少 high/medium 情报。让 LLM 看出"传播该候选的群本身是否高价值"。**启动时计算一次、内存复用**，不入盘。

**Stage 1 LLM 返回 schema**（强制 JSON 数组，复用现有 `_parse_response` 模式）：

```json
[
  {
    "index": 0,
    "decision": "advance",
    "confidence": "high",
    "reason": "来源群均为高强度抖音黑产群，candidate 名称含 douyinhao，count=7"
  }
]
```

**Stage 1 分流**：

| LLM `decision` | 行为 |
|---|---|
| `reject` | 写 `llm_verdict={verdict: llm_rejected, stage: 1}`，**不进 Stage 2**（省 token） |
| `advance` | 进 Stage 2 拿原文细判 |
| `uncertain` | 进 Stage 2，但 Stage 2 阈值更严（见 5.2） |

### 5.2 Stage 2：来源消息原文细判（贵，单条）

**目的**：用真正的上下文确认 candidate 在交易/招揽/工具分享语境里出现，避免误批。

**输入证据**：Stage 1 全部信息 **+ 候选被提到时的来源消息原文**：

```
候选：douyinhao88
出现 7 次，最早 2026-06-05，最近 2026-06-08
来源记录（最多 3 条）：
[1] 群=公群99, msg_id=123456, channel=text
原文："出抖音老号 实名 已养30天 联系 @douyinhao88"

[2] 群=抖音实名, msg_id=789, channel=forward
原文："转发自 @douyinhao88 的频道：今日特价老号..."

[3] 群=刷粉接单, msg_id=4012, channel=text
原文："想要稳定货源加 @douyinhao88，价格美丽"
```

原文从 `output/raw/*.json` 按 `(group_name, msg_id)` 反查 —— 现有 raw export 是按"日期+群名"分文件的 JSON 数组，每个元素含 `msg_id`，反查就是一次启动期建索引 + 内存查询。

**Stage 2 LLM 返回 schema**（单条对象）：

```json
{
  "decision": "approve",
  "confidence": "high",
  "risk_type": "账号交易",
  "reason": "三条来源消息均为抖音老号交易语境，candidate 是卖家 telegram 联系方式"
}
```

**Stage 2 → 最终 verdict 的映射表**：

| Stage1 决策 | Stage2 决策 + 置信度 | 最终 `llm_verdict.verdict` | `status` 是否动（仅 `--write-config` 时） | 是否进 auto-join 队列（仅 `--auto-join` 时） |
|---|---|---|---|---|
| advance | approve + high | `llm_approved_high` | pending → approved | ✅ 是 |
| advance | approve + medium | `llm_approved_medium` | pending → approved | ❌ 否 |
| advance | approve + low | `llm_approved_low` | 不动 | 否 |
| advance | reject | `llm_rejected` | 不动 | 否 |
| uncertain | approve + high | 视同 medium（**降一级**） | pending → approved | ❌ 否 |
| uncertain | approve + medium/low | 视同 low（降一级） | 不动 | 否 |
| uncertain | reject | `llm_rejected` | 不动 | 否 |
| reject (Stage1) | n/a | `llm_rejected` | 不动 | 否 |

**私密群（`key` 以 `+` 开头）置信度自动降一级**：
- 私密群没有 username 语义，原文也通常只有"加 +xxx"一行，证据天然弱
- Stage 2 LLM 给出 high → 实际写入 medium
- Stage 2 LLM 给出 medium → 实际写入 low
- 通过 `--no-include-private` 可以彻底跳过私密群 review

**降级叠加规则**：私密群降级 + Stage1=uncertain 降级可能同时发生，规则是**降级累加**（high → medium → low），最低封顶在 low（不会变成 reject）。例：
- 公开群 + advance + approve + high → `llm_approved_high`
- 公开群 + uncertain + approve + high → 降一级 → `llm_approved_medium`
- 私密群 + advance + approve + high → 降一级 → `llm_approved_medium`
- 私密群 + uncertain + approve + high → 降两级 → `llm_approved_low`
- 私密群 + uncertain + approve + medium → 降两级 → `llm_approved_low`（封顶）

**原文未找到降级**（错误处理表里）：来源消息原文反查失败导致的"置信度降一级"也走同一条降级链路，会与上面两条叠加。

---

## 6. 命令与 flag

```bash
tg-crawler candidates llm-review [OPTIONS]
```

| flag | 默认 | 说明 |
|---|---|---|
| `--max-candidates N` | 200 | 单次 review 最多看 N 个候选；超过时按 `score` 降序取头部。`score = count × max(source_groups_intel_score.high, default=1)` |
| `--stage1-batch-size N` | 30 | Stage 1 每批喂多少候选给 LLM |
| `--write-config` | false | 把 `llm_approved_high/medium` 的 status 改为 approved 并 append 到 `config.groups`（去重） |
| `--auto-join` | false | 在 `--write-config` 基础上，对 `llm_approved_high` 走 `JoinThrottle` 限流加群（medium 只写 config 不加群）。**单独使用 `--auto-join` 不带 `--write-config` 时报错退出**，避免 "加了群但没记 config" 的不一致状态 |
| `--force-rereview` | false | 忽略增量重审条件，强制重看所有 `status=pending` 候选 |
| `--dry-run` | false | 走完两阶段，但不写 verdict、不动 status、不加群，只打印 LLM 决策摘要 |
| `--include-private/--no-include-private` | true | 是否 review 私密群（key 以 `+` 开头）。默认 true，但所有私密群置信度自动降一级 |

**典型用法序列**：

```bash
# 第一次：纯观察，看 LLM 选了啥
tg-crawler candidates llm-review --max-candidates 50 --dry-run

# 看着合理的话，正式跑一遍并写 verdict（不动 status）
tg-crawler candidates llm-review --max-candidates 200

# 看 candidates list，确认 LLM 的批准合理后，落到 config（仍不加群）
tg-crawler candidates llm-review --write-config

# 真要自动加群时
tg-crawler candidates llm-review --write-config --auto-join
```

---

## 7. 错误处理

| 失败场景 | 行为 |
|---|---|
| LLM 调用失败（网络 / API error） | 不写 verdict，跳过该批次，日志 warning，**不让整个命令挂掉**（延续 `LLMFilter` 现有约定） |
| Stage 1 LLM 返回数量与输入不匹配 | 整批跳过，不部分写入（避免 index 错位），日志 warning |
| Stage 2 单个候选 LLM 失败 | 该候选无 verdict，下次 review 时被增量重审拾起 |
| Stage 2 LLM 返回 JSON parse 失败 | 同上，跳过 |
| 来源消息原文反查失败（raw 文件被删 / msg_id 找不到） | Stage 2 仅看 metadata，置信度自动降一级；reason 里标注 `[原文未找到]` |
| `output/raw/` 整个目录不存在 | Stage 2 全部退化为 metadata-only + 置信度降级；命令开头打印 warning |
| `output/filtered/` 整个目录不存在 | `source_groups_intel_score` 全部为空，Stage 1 仅靠 candidate metadata 判断；命令开头打印 warning |
| candidate 在 yaml 里但 sources 为空 | 跳过该 candidate（无任何证据可判） |

---

## 8. 可观测性：命令结尾汇总

```
📊 LLM Review Summary
  Reviewed:           180 candidates (out of 6824 pending)
  Stage 1 reject:      95   → llm_rejected
  Stage 1 advance:     68   → Stage 2
  Stage 1 uncertain:   17   → Stage 2 (with stricter threshold)
  Stage 2 approve:     66   (high=23 / medium=31 / low=12)
  Stage 2 reject:      19   → llm_rejected
  Final verdicts written: 180 (114 rejected, 66 approved)
  LLM tokens used:     ~85k input / ~12k output
  --write-config: appended 54 links to config.groups (high+medium)
  --auto-join:    joined 8 groups, 15 queued (hit daily_limit=20)
```

每个候选的 LLM `reason` 写进 verdict，方便事后 `grep 'douyinhao88' config/discovered_groups.yaml -A 8` 查为何批/拒。

附带改动：`tg-crawler candidates list` 现有命令加 `--llm-verdict` 过滤选项（可选值同 `verdict` 闭集 + `none`），用于"列出所有 LLM 看过且批准为 high 的"等场景。

---

## 9. 测试策略

### Unit 层（mock LLM 客户端）

- `CandidatePool.pending_for_review` 的过滤逻辑：
  - 没 verdict 的 pending 候选 → 选中
  - 有 verdict 但 `count` 翻倍 → 选中（增量重审）
  - 有 verdict 且 `reviewed_at` 超 30 天 → 选中
  - status 是 approved / rejected → 跳过
- Stage 1 → Stage 2 的分流规则（advance / uncertain / reject 三条路径分别构造一个 case）
- Stage 2 私密群自动降级
- 来源原文反查命中 / 缺失两种路径
- `apply_llm_approvals` 不重复添加 `config.groups` 已有的链接
- `--auto-join` 不带 `--write-config` 时报错
- `--dry-run` 不写盘任何状态

### 集成层（手动跑，CI 跳过）

- 真跑一次 `--dry-run --max-candidates 5`，确认 prompt / parse / 写盘端到端不挂
- 真跑一次 `--max-candidates 5`（不带 write-config / auto-join），确认 verdict 写入 yaml 格式正确

---

## 10. 实现顺序（粗排，详细分步留给 plan 阶段）

1. `RawMessageLookup` + `IntelStatsAggregator` 两个纯函数模块（无 Telethon、无 LLM 依赖，最容易独立测试）
2. `CandidatePool` 扩字段：`pending_for_review` / `set_llm_verdict` / `apply_llm_approvals`
3. `CandidateReviewer`：Stage1 / Stage2 / finalize（mock LLM 单测优先）
4. `main.py` 新子命令 `candidates llm-review` + flag 解析 + 汇总打印
5. `candidates list --llm-verdict` 附带改动
6. README 增加 "LLM 自动审查" 章节，给典型命令序列

每步独立可测、独立可提交。

---

## 11. 与现有功能的兼容性

- 现有 `candidates approve/reject/list/stats` 命令不需要修改即可继续工作；老的 yaml 没有 `llm_verdict` 字段也兼容
- 现有 `crawl` / `crawl-bot` / `probe-bot-lookup` 流程完全不受影响
- 候选 yaml 的 schema 变更是 **向后兼容的可选字段**，老版本工具读新 yaml 时会忽略 `llm_verdict`；新版本读老 yaml 时所有候选都被视为"未 review"
- `JoinThrottle` 直接复用，不修改其行为；`--auto-join` 触发的加群和现有 `candidates approve` 走同一条限流路径，daily_limit 共享

---

## 12. 风险与回退

- **LLM 误批一批垃圾群**：用户可以手动 `candidates reject <key>` 把 status 改回 rejected；下次 LLM 不会再碰
- **LLM 把账号 join 到 trap 群导致风控**：默认 `--auto-join` 关闭、且只有 `confidence=high` 才进 join 队列；`JoinThrottle` 的 daily_limit=20 限制爆炸半径
- **LLM 模型切换后 verdict 失效**：`llm_verdict.model` 字段留痕，可以用 `--force-rereview` 重跑；或者写一个一次性脚本删除所有 `model != current_model` 的 verdict
- **Token 成本失控**：`--max-candidates` 默认 200 是硬上限；Stage1 砍掉一大半后 Stage2 输入显著缩水
