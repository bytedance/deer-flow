# 候选群反查能力探测（probe-bot-lookup）— 设计

| 字段 | 值 |
|---|---|
| 日期 | 2026-06-06 |
| 状态 | Draft |
| 上下文 | `discovered_groups.yaml` 已有 624 个候选群（72% 仅出现 1 次，53% 是私密 invite-only）；下一步要让 LLM 自动判定该不该爬。判定前必须先回答：搜群 bot（@JISOU）能反查到这些候选的多少？ |

## 目标

跑一次性的探测脚本，分层抽样 30 个候选喂给 @JISOU，量化两件事：

1. **公开群命中率**：bot 是否能用 username 反查到该群本身或其内容
2. **私密群命中边界**：bot 对裸 invite hash 是否如预期一样无能为力

产出一份 JSON 原始数据 + Markdown 人读报告，供后续"二级扩展"设计决定 LLM 的输入材料。

## 非目标（YAGNI）

- 不动 `CandidatePool`、不写状态、不改 yaml
- 不调用 LLM
- 不做置信区间 / 统计学严谨性
- 不实现自动化跑批，单次手动触发即可
- 不评估 @JISOU 之外的 bot（同一脚本未来可换 bot 重跑）

## 模块划分

```
                    ┌─────────────────────────┐
                    │ CLI: probe-bot-lookup   │
                    └──────────┬──────────────┘
                               │
            ┌──────────────────┼──────────────────┐
            ▼                  ▼                  ▼
   ┌────────────────┐ ┌──────────────────┐ ┌──────────────────┐
   │ CandidatePool  │ │ Sampler          │ │ ProbeReporter    │
   │ (read-only)    │ │ - 6 layers × 5   │ │ - JSON dump      │
   │ list_all()     │ │ - seeded RNG     │ │ - Markdown       │
   └────────┬───────┘ └────────┬─────────┘ └──────────────────┘
            │                  │
            └────────┬─────────┘
                     ▼
          ┌─────────────────────────┐
          │ ProbeRunner             │
          │ - per candidate:        │
          │   acquire → query →     │
          │   parse → classify      │
          └──────────┬──────────────┘
                     │ reuses
            ┌────────┼────────┬──────────────────┐
            ▼        ▼        ▼                  ▼
    BotSearchClient  BotQuery  BotResponse  TGClient
                     Throttle  Parser
```

各模块通过窄接口交互、能独立单测：

| 模块 | 文件 | 接口 |
|---|---|---|
| `Sampler` | `tg_intel_crawler/probe/sampler.py` | `Sampler(seed).draw(candidates, per_layer=5) → list[SampledCandidate]` |
| `ProbeRunner` | `tg_intel_crawler/probe/runner.py` | `await runner.run(samples) → list[ProbeRecord]` |
| `ProbeReporter` | `tg_intel_crawler/probe/reporter.py` | `reporter.write(records, dest_dir)` |

注意：**新建 `tg_intel_crawler/probe/` 包**，与 `collector/` 平级。理由：探测属于一次性诊断工具，不是采集流水线，逻辑独立、生命周期短，混进 collector 会模糊职责。`__init__.py` 留空。

## 关键决策

| 主题 | 决策 | 理由 |
|---|---|---|
| 采样规模 | 6 层 × 5 = 30 个 | 总数受 `bot_search.max_queries_per_run`（默认 30）天然约束 |
| 分层维度 | (公开/私密) × (count=1, 2-9, ≥10) | 量级跨越大（1 vs 1181），单一抽样会被 count=1 的 448 个长尾淹没 |
| 不足层处理 | 该层 < 5 时取实际数量，不补到其他层 | 保留分层语义；报告里显式标注实际抽到几个 |
| 公开群 query | 直接发 `key`（不加 @） | bot 在 chat 里不会把 `@xxx` 当 mention，发 plain string 更稳 |
| 私密群 query | 发 `key.lstrip('+')`（裸 invite hash） | 验证 bot 是否有"邀请链接索引"；预期 0 命中但要实测 |
| 限流复用 | `BotQueryThrottle(interval, cap)` 沿用 config.bot_search 设置 | 与 `crawl-bot` 同一限流壳，不会出第二个节流 |
| 错误处理 | 单候选异常只标 `error` 分类，不中断整次探测 | 报告要能跑完 30 个，单点失败不打断 |
| 不污染候选池 | `CandidatePool` 只调 `list_all()` 读，不调 `merge`/`flush` | 探测必须可重复跑，不能改状态 |
| 报告位置 | `output/probe/bot_lookup_<UTC_date>.{json,md}` | 与 `output/raw/`、`output/filtered/` 同根，不混在 raw 里 |

## 数据结构

### `SampledCandidate`

```python
@dataclass
class SampledCandidate:
    key: str                    # 候选 key，e.g. "douyinhao88" or "+abcXYZ"
    count: int                  # CandidatePool 里的累计 count
    invite_hash: str | None     # 私密群保留 hash 用于复看
    candidate_type: str         # "public" | "private"
    stratum: str                # "L1".."L6"
```

### `ProbeRecord`

```python
@dataclass
class ProbeRecord:
    candidate: SampledCandidate
    query_sent: str             # 实际发给 bot 的 query 字符串
    reply_status: str           # "ok" | "empty_reply" | "error"
    reply_raw: str              # bot 原始回复（截断到 4096 char）
    error: str | None           # 异常类名+消息，仅 reply_status=error 时填
    previews_count: int
    matched_preview: dict | None  # channel_username == key 的第一条 preview（dict 化）
    classification: str         # 见下表
```

### 命中分类

| 分类 | 判定（按顺序短路） |
|---|---|
| `error` | 抓到任何异常（query 阶段或 parse 阶段）|
| `empty_reply` | bot reply 为 None / 空字符串 |
| `direct_hit` | reply 解析出的 previews 中存在 `channel_username.lower() == key.lower()` |
| `indirect_hit` | previews 非空但无 `direct_hit` |
| `no_results` | reply 非空但 `previews == []` |

注：`direct_hit` 仅对公开候选有意义（私密候选 key 是 `+hash`，不会等于任何 channel_username），所以私密候选实际上只会落进后三档。

## 流程

### 单候选探测

```
acquire throttle slot              # 默认 10s 间隔
  → BotSearchClient.query(query_sent, timeout=15s)
  → if reply is None / "":  status=empty_reply, classification=empty_reply
  → else:
      try:
        previews = BotResponseParser.parse(reply, query=..., bot=...)
        if direct_hit:    classification=direct_hit
        elif previews:    classification=indirect_hit
        else:             classification=no_results
      except Exception as e:
        status=error, classification=error
```

### 整体跑批

```
load CandidatePool (read-only)
  → Sampler.draw(seed=42, per_layer=5) → 30 个 SampledCandidate
  → ensure bot reachable (BotSearchClient.ensure_available)
  → for each sample:
       record = await runner.probe(sample)
       records.append(record)
       progress log
  → ProbeReporter.write(records, dest=output/probe/)
```

## CLI

新增一个独立子命令（不进 `crawl` / `crawl-bot` 主流程）：

```
tg-crawler probe-bot-lookup \
  [--sample-size 30] \
  [--seed 42] \
  [--bot @JISOU] \
  [--report-dir output/probe]
```

| flag | 默认 | 说明 |
|---|---|---|
| `--sample-size` | 30 | 总采样数；若小于 30 则按比例缩减各层 |
| `--seed` | 42 | 随机种子，复现用 |
| `--bot` | `bot_search.bots[0]` | 想换 bot 时覆盖 |
| `--report-dir` | `output/probe` | JSON + Markdown 输出位置 |

`--sample-size` 缩减规则：均分 6 层、向下取整、余数从 L3/L6（高 count 层）开始填补。例如 `--sample-size 12` → 各层 2，余 0；`--sample-size 15` → 各层 2 余 3，分给 L3、L6、L2。

## 产出物

### `output/probe/bot_lookup_<UTC date>.json`

```json
{
  "meta": {
    "bot": "@JISOU",
    "sample_size": 30,
    "seed": 42,
    "generated_at": "2026-06-06T12:34:56+00:00",
    "candidate_pool_total": 624
  },
  "records": [
    {
      "candidate": {
        "key": "douyinhao88",
        "count": 246,
        "candidate_type": "public",
        "stratum": "L3"
      },
      "query_sent": "douyinhao88",
      "reply_status": "ok",
      "reply_raw": "广告:...\n🌄 ...",
      "previews_count": 4,
      "matched_preview": {
        "channel_username": "douyinhao88",
        "msg_id": 12345,
        "text": "..."
      },
      "classification": "direct_hit",
      "error": null
    }
  ]
}
```

### `output/probe/bot_lookup_<UTC date>.md`

固定结构：

```markdown
# Bot Lookup Probe — 2026-06-06

bot: @JISOU
sample: 30 / 624 (seed=42)

## 命中分布
| 分类           | 公开 | 私密 | 合计 |
|----------------|------|------|------|
| direct_hit     |  X   |  -   |  X   |
| indirect_hit   |  …   |  …   |  …   |
| no_results     |  …   |  …   |  …   |
| empty_reply    |  …   |  …   |  …   |
| error          |  …   |  …   |  …   |

## 按层细分
| 层 | 描述              | n | direct | indirect | none | empty | err |
|----|-------------------|---|--------|----------|------|-------|-----|
| L1 | 公开 count=1      | 5 |   …    |    …     |  …   |   …   |  …  |
| L2 | 公开 count 2-9    | 5 |   …    |    …     |  …   |   …   |  …  |
| L3 | 公开 count ≥10    | 5 |   …    |    …     |  …   |   …   |  …  |
| L4 | 私密 count=1      | 5 |   -    |    …     |  …   |   …   |  …  |
| L5 | 私密 count 2-9    | 5 |   -    |    …     |  …   |   …   |  …  |
| L6 | 私密 count ≥10    | 5 |   -    |    …     |  …   |   …   |  …  |

## 典型样本
### direct_hit · douyinhao88 (L3, count=246)
query: `douyinhao88`
matched preview:
> 🌄 抖音黑产... t.me/douyinhao88/12345

### indirect_hit · ...
### no_results · ...
### empty_reply · ...
### error · ...
```

每分类只展示一条典型样本（有就放，没有就跳过那一节），避免报告过长。

## 错误与边界

| 场景 | 处理 |
|---|---|
| `bot_search.bots` 为空或全部不可达 | 立刻报错退出，不跑探测 |
| 候选池为空 / 不存在 | 立刻报错退出 |
| 候选池总数 < sample_size | 警告并按实际可抽数量执行 |
| 单层候选数 < 期望抽样数 | 该层取全部，报告标注实际抽到几个 |
| `BotQueryLimitExceeded` 中途触发 | 停止 query，已收集到的 records 仍写报告，meta 标记 `truncated: true` |
| `asyncio.TimeoutError` | `BotSearchClient.query` 已返回 None → `empty_reply` |
| `ChatWriteForbidden` / 账号被 bot 拉黑 | 抓到异常 → `error` 分类，记录类名 |
| `reply_raw` 超长 | 截断到 4096 字符，末尾加 `... [truncated]` 标记 |
| 报告目录不存在 | `mkdir -p` 创建 |
| 同一天重复跑 | 文件名带 ISO date，不带时间；重复跑会覆盖。如需保留多次，手动改名或加 `--report-suffix` |

## 测试计划

| 模块 | 测试要点 |
|---|---|
| `Sampler` | 固定 seed 输出稳定；分层数学正确；候选池 < per_layer 时按实际取；`--sample-size` 缩减分配公平；空候选池报错 |
| 命中分类逻辑 | parametrize: `direct_hit` / `indirect_hit` / `no_results` / `empty_reply` / `error` 各一例；大小写不敏感比较 |
| `ProbeRunner` | mock `BotSearchClient` + `BotResponseParser`：单候选 happy path、超时、limit exceeded 中途停止、未知异常路径 |
| `ProbeReporter` | JSON round-trip；Markdown 列计数正确；分类内 0 条时不输出该子节；reply_raw 截断 |
| 端到端 | mock bot client 跑 6 候选 × 4 分类，断言输出 JSON 总条数 + Markdown 表格命中分类计数 |

## 实施顺序

1. `Sampler`（纯函数，最容易先上）
2. 数据结构 (`SampledCandidate`、`ProbeRecord`) + 命中分类纯函数
3. `ProbeReporter`（输入是 list，无 IO 依赖外部）
4. `ProbeRunner`（mock bot client）
5. CLI 串联（复用 `_crawl_bot_async` 中已有的 bot 选择 / throttle 构造）
6. 端到端跑 mock，断言报告
7. 真实环境单次跑（`--sample-size 6` smoke），核对一份报告，再跑 30
8. README 增加一节 "candidate-pool diagnostics"，commit

## 后续决策树（不在本 spec 范围内）

报告跑完后、写"二级扩展"spec 时根据数字决策：

| 公开群 direct_hit 率 | 决策 |
|---|---|
| < 20% | bot 反查不值得；LLM 输入 = 候选上下文 + `get_entity` (title/about) |
| 20–60% | 公开群分两路：bot 命中走 bot 文本，未命中 fallback `get_entity` |
| > 60% | 公开群标配 bot 反查 + LLM |

私密群无论数字多少都走另一路，可能选项：
- 候选上下文 + LLM 自信度评分（最便宜）
- 试探性低成本 join 5 个看群内活跃度（最贵但最准）
- 二者结合：先 LLM 排序，对 top-K 做小批量试加群

这一层的设计在拿到本探测报告后单独写 spec。
