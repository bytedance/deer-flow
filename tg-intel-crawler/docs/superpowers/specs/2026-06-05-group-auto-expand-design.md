# 群组自动扩展（限流 + 反向发现 + 扫已加群）— 设计

| 字段 | 值 |
|---|---|
| 日期 | 2026-06-05 |
| 状态 | Draft → Approved |
| 上下文 | tg-intel-crawler 当前 `GroupFinder` 只能"按关键词搜公开群+裸 join"，无限流、无去重、无反向扩展 |

## 目标

让爬虫的群组覆盖面**自动扩展**，同时不让 Telegram 风控封号。具体三件事：

1. **加群限流**（防风控）：所有 `JoinChannelRequest` 走统一限流壳；FloodWait 自动 sleep 重试；加过的群不再加。
2. **反向滚雪球**（发现）：`crawl` 抓到的每条消息，顺手挖出"它提到的其他群"，沉淀到候选池。
3. **扫已加入群**（同步）：直接读账号当前已加入的群/频道作为爬取目标 —— 你手动加的群当天就能爬。

## 非目标（YAGNI）

- 不接搜群 bot（V2 考虑，预留 `DiscoverySource` 抽象命名空间）
- 不做"多次同现才加"的阈值过滤（候选池靠人审）
- 不做 invite hash 自动展开成群名
- 不并发 join（限流本来就要串行）

## 模块划分

```
                            ┌──────────────────────────┐
                            │   JoinThrottle           │
                            │ - 已加群 set (iter_dialogs│
                            │   预热 + 加群后补充)     │
                            │ - 30~90s 随机间隔        │
                            │ - 每日 N 个上限          │
                            │ - FloodWait 自动 sleep   │
                            └──────────────┬───────────┘
                                           │ 被以下所有路径调用
       ┌──────────┬─────────────────┬──────┴─────────────┬─────────────────┐
       ▼          ▼                 ▼                    ▼                 ▼
GroupFinder  crawl 管道       candidates approve   discover --auto-join   (V2: bot)
   .join         │                  ▲
                 ▼                  │
       ┌────────────────────────┐   │
       │   GroupExtractor       │   │
       │ - msg.text 正则        │   │
       │ - msg.entities         │   │
       │ - msg.forward_from     │   │
       │ - (opt) sender.bio     │   │
       └─────────┬──────────────┘   │
                 │                  │
                 ▼                  │
       ┌────────────────────────┐   │
       │   CandidatePool        │   │
       │ - discovered_groups.   │   │
       │   yaml 持久化          │   │
       │ - status: pending /    │   │
       │   approved / rejected  │   │
       │ - count, sources[]     │───┘
       └────────────────────────┘

       ┌────────────────────────┐
       │ JoinedGroupsScanner    │  ─→ 注入 crawl 目标列表
       │ - iter_dialogs()       │
       │ - 过滤 user / bot      │
       └────────────────────────┘
```

四个模块都通过窄接口交互，能各自单独测试：

| 模块 | 文件 | 接口 |
|---|---|---|
| `JoinThrottle` | `tg_intel_crawler/collector/join_throttle.py` | `await throttle.acquire(username) → bool`、`mark_joined(username)`、`is_already_joined(...)` |
| `GroupExtractor` | `tg_intel_crawler/collector/group_extractor.py` | `extract_from(messages) → list[CandidateSignal]` |
| `CandidatePool` | `tg_intel_crawler/collector/candidate_pool.py` | `merge(signals)`、`list(status=...)`、`approve(keys)`、`reject(keys)` |
| `JoinedGroupsScanner` | `tg_intel_crawler/collector/joined_scanner.py` | `await list_joined(...) → list[JoinedGroup]` |

## 关键决策

| 主题 | 决策 | 理由 |
|---|---|---|
| 候选池存储 | `config/discovered_groups.yaml`（与 `config.yaml` 平级，`.gitignore` 屏蔽） | 简单、人可读、能手改 |
| 候选 key | 优先 `username`，否则 invite hash（私密群） | 同一群被多源提及自动合并 |
| 已加群判定 | 启动时 `iter_dialogs()` 预热，构建 `set[username]` + `set[chat_id]` | 零额外 API；用户退群后下次启动会自动复位 |
| 限流默认值 | `min_interval: 30`、`max_interval: 90` 秒；`daily_limit: 20`；FloodWait 自动 sleep 重试一次 | 经验值，留 config 旋钮 |
| 候选写盘时机 | 每爬一个群结束后 + 每条 realtime 消息后增量 merge | 中途崩溃不丢候选 |
| Bio 抽取 | `config.discovery.fetch_sender_bio: false`（默认） | 避免 get_entity quota 被烧 |
| CLI | 新增 `candidates {list,approve,reject,stats}` + `groups {list-joined,sync}` + `crawl --include-joined/--joined-only/--exclude` | 与现有子命令风格一致 |

## 数据结构

### `discovered_groups.yaml`

```yaml
candidates:
  douyinhao88:                       # key = username（私密群用 invite hash）
    invite_hash: null
    first_seen: 2026-06-05T08:30:00
    last_seen:  2026-06-05T22:15:00
    count: 7                         # 出现次数
    status: pending                  # pending / approved / rejected
    sources:                         # 最多保留 3 条溯源
      - group: 公群99
        msg_id: 123456
        channel: text                # text / forward / entity / bio
      - group: 抖音实名
        msg_id: 789
        channel: forward
  "+abc123xyz":
    invite_hash: abc123xyz
    first_seen: 2026-06-05T09:00:00
    count: 1
    status: pending
    sources: [...]
```

### `CandidateSignal`（内存）

```python
@dataclass
class CandidateSignal:
    username: str | None        # 公开群: "douyinhao88"
    invite_hash: str | None     # 私密群: invite hash
    channel: str                # text / forward / entity / bio
    source_group: str           # 来源群名
    source_msg_id: int
    seen_at: datetime
```

### `JoinedGroup`

```python
@dataclass
class JoinedGroup:
    chat_id: int
    title: str
    username: str | None
    members_count: int | None
    type: str                   # group / channel / supergroup
    link: str                   # https://t.me/<username> 或 chat_id 形式
```

## 流程

### crawl 一个群结束后

```
fetch_history(group, days=7)              # 已有
  → list[MessageData]
  → exporter.export_raw(...)              # 已有
  → keyword_filter.matches(...) → llm.analyze   # 已有
  → exporter.export_filtered(...)         # 已有
  → GroupExtractor.extract_from(messages) # 新增
      ↳ 对每条 msg：text 正则、entities、forward_from
      ↳ 返回 list[CandidateSignal]
  → CandidatePool.merge(signals, source=group_name) → 写盘
```

### crawl --include-joined 启动时

```
iter_dialogs() 预热                       # 一次性
  ├─→ JoinThrottle 维护已加群 set
  └─→ JoinedGroupsScanner 列已加入群

config.groups + scanner.list_joined() − config.exclude_joined → dedupe → fetch loop
```

### candidates approve 时

```
load discovered_groups.yaml
  → for each approved key:
      JoinThrottle.acquire(key)           # 限流 + 已加群短路
      GroupFinder.join_group(key)
      mark_joined(key)
      append to config.groups
      status: pending → approved
```

## 错误与边界

| 场景 | 处理 |
|---|---|
| `FloodWaitError` < 60s | Telethon 自带 `flood_sleep_threshold=60` 自动 sleep |
| `FloodWaitError` ≥ 60s | `JoinThrottle` catch → sleep `e.seconds` 后重试一次；二次失败 reject |
| `ChannelPrivateError` / `InviteHashExpiredError` | 直接打 status=rejected，不重试 |
| 其他网络异常 | 保持 status=pending，下次再试 |
| `iter_dialogs` 失败 | warning + fallback：`is_already_joined` 改用 `get_entity` |
| 大候选池（>5000）`yaml.dump` 慢 | 改用增量 append，不全量重写 |
| `@username` 中文误判 | 严格按 TG 规则（5~32 字符、首字母为字母、`[A-Za-z][A-Za-z0-9_]{4,31}`） |
| 同一群多源提及 | `sources` 去重保留**最先 3 条**，count 累加 |
| 私密群（无 username） | key 用 `invite_hash`，`link` 形如 `https://t.me/+<hash>` |

## CLI

新增 / 改动：

| 命令 | 说明 |
|---|---|
| `tg-crawler crawl --days 7 --include-joined` | 把账号当前已加群并入爬取目标 |
| `tg-crawler crawl --joined-only` | 只爬已加入群，忽略 config.groups |
| `tg-crawler crawl --exclude "@a,@b"` | 排除某些群（精确 username/chat_id） |
| `tg-crawler candidates list [--status pending]` | 表格展示候选池 |
| `tg-crawler candidates approve <keys>` | 批准+加群+写入 config.groups |
| `tg-crawler candidates reject <keys>` | 标记拒绝，不再出现 |
| `tg-crawler candidates stats` | 候选池数量统计 |
| `tg-crawler groups list-joined` | 只列账号当前已加群（不写盘） |
| `tg-crawler groups sync` | 把已加群合并写入 config.groups |

## config 新增

```yaml
discovery:
  fetch_sender_bio: false          # 是否抽取发送者 bio 里的链接
  bio_rate_limit_per_minute: 30
  candidates_path: ./config/discovered_groups.yaml

  include_joined: false            # crawl 默认是否并入已加群
  exclude_joined: []               # 永久黑名单（username 或 chat_id）
  scan_includes_channels: true     # 频道是否纳入

join:
  min_interval: 30                 # 加群最小间隔（秒）
  max_interval: 90
  daily_limit: 20                  # 每天最多加多少个群
  flood_retry: true                # FloodWait 是否自动重试一次
```

## 测试计划

| 模块 | 测试要点 |
|---|---|
| `GroupExtractor` | 正则 fixture：`https://t.me/foo`、`@bar`、混在中文里、私密群 `t.me/+xxx`、误识别（`@user你好` 不该把"你好"算进 username）；forward_from；entities |
| `CandidatePool` | yaml round-trip；merge 累加 count；status 切换；sources 截断到 3 条；空文件 / 不存在文件 |
| `JoinThrottle` | freezegun mock 时间；间隔下限；每日上限；FloodWait 重试；已加群短路 |
| `JoinedGroupsScanner` | mock `iter_dialogs`：user/bot 过滤；include_channels；exclude；私密群字段降级 |
| `crawl --include-joined` | 端到端：mock scanner + fetcher，验证去重 |

## 实施顺序

1. `GroupExtractor`（纯函数最容易先上）
2. `CandidatePool`（独立 IO，无依赖）
3. `JoinedGroupsScanner`（mock client.iter_dialogs）
4. `JoinThrottle`（mock 时间）
5. CLI 串联（`candidates`、`groups list-joined/sync`、`crawl --include-joined`）
6. README 更新
7. 端到端跑通 + commit
