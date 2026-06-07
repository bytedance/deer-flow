# ThreatIntel-Agent · tg-intel-crawler

> Telegram + Twitter 黑灰产情报爬虫 —— 字节跳动相关风险监控

本项目通过 **Telethon (MTProto)** 爬取 Telegram 频道/群组消息，通过 **tikhub.io** 爬取 Twitter/X 数据，再经过两级过滤（关键词 → LLM 语义分析），输出结构化的情报记录到 JSON / CSV。

> ⚠️ **关于敏感信息（请先读这一段再开始）**
>
> - **不要把真实凭证写进任何会被 commit 的文件**。`config/config.yaml`、`*.session`、`output/` 已在 `.gitignore` 中显式忽略。
> - 第一次使用请：`cp config/config.example.yaml config/config.yaml`，然后在新文件里填 `api_id` / `api_hash` / `api_key` 等。
> - 如果你曾把凭证 push 到远端，立刻 **吊销/轮换** 对应的 Telegram、tikhub.io、LLM 服务商凭据，光删文件不算修复。

## 三种典型用法（详见后文章节）

```bash
# 用法 A：你手动加群，爬虫跟进
tg-crawler crawl --include-joined --days 7

# 用法 B：让爬虫从消息里反向滚雪球
tg-crawler crawl --days 7                           # 边爬边记候选
tg-crawler candidates list                          # 看候选池
tg-crawler candidates approve foo bar +abcXYZ       # 限流加群+并入 config

# 用法 C：定期把已加群同步进配置（不爬）
tg-crawler groups sync

# 用法 D：通过搜群 bot（@JISOU 等）按关键词检索情报
tg-crawler crawl-bot --keywords "抖加,买号"
```

加群默认 30~90s 一个、每天上限 20，FloodWait 自动 sleep 重试一次。已加过的群任何路径都自动短路。

---

## 目录

- [项目结构](#项目结构)
- [安装](#安装)
- [配置](#配置)
- [快速开始](#快速开始)
- [数据爬取流程](#数据爬取流程)
  - [1. 登录 Telegram (TGClient)](#1-登录-telegram-tgclient)
  - [2. 发现群组 (GroupFinder)](#2-发现群组-groupfinder)
  - [3. 抓取消息 (MessageFetcher)](#3-抓取消息-messagefetcher)
  - [4. 抓取 Twitter (TwitterFetcher)](#4-抓取-twitter-twitterfetcher)
- [数据清洗流程](#数据清洗流程)
  - [Step 1：关键词过滤 (KeywordFilter)](#step-1关键词过滤-keywordfilter)
  - [Step 2：LLM 语义过滤 (LLMFilter)](#step-2llm-语义过滤-llmfilter)
- [数据保存 (Exporter)](#数据保存-exporter)
- [CLI 命令汇总](#cli-命令汇总)
- [群组自动扩展](#群组自动扩展)
  - [用法 A：你手动加群，爬虫跟进](#用法-a你手动加群爬虫跟进最简单)
  - [用法 B：让爬虫从消息里反向滚雪球](#用法-b让爬虫从消息里反向滚雪球推荐主路径)
  - [用法 C：把已加入群一次性同步到配置](#用法-c把已加入群一次性同步到配置不爬)
- [通过搜群 bot 检索情报（crawl-bot）](#通过搜群-bot-检索情报crawl-bot)
  - [快速开始](#快速开始-1)
  - [完整用法](#完整用法)
  - [各 flag 详解](#各-flag-详解)
- [扩展与二次开发](#扩展与二次开发)

---

## 项目结构

```
tg-intel-crawler/
├── config/
│   ├── config.example.yaml  # 配置模板（已脱敏）— 复制成 config.yaml 后填值
│   ├── config.yaml          # 主配置：TG/Twitter/LLM/输出（被 .gitignore 屏蔽）
│   ├── keywords.yaml        # 关键词词表（products × actions）
│   └── crawler_session.session  # Telethon 会话，首次登录后生成（被 .gitignore 屏蔽）
├── tg_intel_crawler/
│   ├── main.py              # CLI 入口（click）
│   ├── collector/
│   │   ├── client.py            # TGClient：Telethon 封装
│   │   ├── group_finder.py      # GroupFinder：搜索/加入群
│   │   ├── group_extractor.py   # GroupExtractor：从消息里挖新群信号
│   │   ├── candidate_pool.py    # CandidatePool：候选池 yaml 持久化
│   │   ├── joined_scanner.py    # JoinedGroupsScanner：列账号已加入群
│   │   ├── join_throttle.py     # JoinThrottle：加群限流 + FloodWait + 已加去重
│   │   ├── message_fetcher.py   # MessageFetcher：历史 + 实时
│   │   ├── twitter_client.py    # TikHub HTTP 客户端
│   │   └── twitter_fetcher.py   # TwitterFetcher：搜索 + 用户推
│   ├── filter/
│   │   ├── keyword_filter.py   # 双维度关键词过滤
│   │   └── llm_filter.py       # LLM 二次过滤
│   ├── storage/
│   │   └── exporter.py      # IntelRecord + JSON/CSV 导出
│   └── utils/
│       ├── rate_limiter.py  # 异步限流
│       └── logger.py
├── output/                  # 运行时生成（被 .gitignore 屏蔽）
│   ├── raw/                 # 原始消息（按日期+群名分文件）
│   └── filtered/            # LLM 命中后的情报（按日期合并）
└── pyproject.toml
```

---

## 安装

需要 **Python 3.11+**：

```bash
git clone https://github.com/meiyang02100033-art/ThreatIntel-Agent.git
cd ThreatIntel-Agent
pip install -e .
# 或
pip install -r requirements.txt
```

主要依赖：`telethon`、`openai`（兼容协议，用于火山方舟）、`httpx`、`click`、`pyyaml`。

---

## 配置

**第一步**：用模板生成自己的配置文件（这一步不能跳过，仓库里没有 `config.yaml`）：

```bash
cp config/config.example.yaml config/config.yaml
```

**第二步**：把真实凭证填进 `config/config.yaml`（该文件已在 `.gitignore` 中，不会被 commit）：

```yaml
telegram:
  api_id: 12345                # 从 https://my.telegram.org 申请
  api_hash: "xxxx"
  phone: "+86xxxxxxxxxx"       # 必须带国家代码
  session_name: crawler_session

llm:
  api_key: "ark-xxx"
  base_url: https://ark.cn-beijing.volces.com/api/v3   # 火山方舟 OpenAI 兼容协议
  model: ep-2026xxxxxx
  batch_size: 15               # 一次喂给 LLM 的消息数

crawl:
  delay_min: 2                 # 限流：每 N 条消息 sleep 一次
  delay_max: 5
  history_days: 7
  download_media: false

twitter:
  api_base: https://api.tikhub.io
  api_key: "xxx"               # tikhub.io 申请
  search_keywords: [...]
  monitor_users: []
  search_type: Latest
  max_pages: 5
  page_size: 20

groups:                        # 监控的 TG 群链接，可由 discover 命令自动写入
  - https://t.me/xxxxx

output:
  dir: ./output
  format: [json, csv]
```

`config/keywords.yaml` 用于本地关键词预过滤，采用 **products × actions** 双维度（必须同时命中产品词和动作词才算匹配）：

```yaml
products: ["抖音", "douyin", "tiktok", "字节", ...]
actions:  ["刷粉", "买号", "卖号", "引流", "解封", ...]
```

> 💡 也可以把敏感字段从 `config.yaml` 抽到环境变量里（自行改造 `load_config`）；`*.session` 会绑定 Telegram 账号，**永远不要 commit**。

---

## 快速开始

```bash
# 1. 交互式填写 Telegram 账号信息（写入 config.yaml）
tg-crawler init

# 2. 按关键词搜索并加入相关公开群组
tg-crawler discover --keywords "抖音买号,刷粉,接码"

# 3. 爬取最近 7 天历史消息 + 实时监听
tg-crawler crawl --mode both --days 7

# 4. （可选）爬取 Twitter
tg-crawler crawl-twitter --days 7
```

首次运行 `crawl` 时会要求输入手机短信验证码，登录态保存在 `config/crawler_session.session`，后续无需再登录。

---

## 数据爬取流程

整体流程：

```
                  ┌──────────────┐
       config ──▶ │   TGClient   │ Telethon 登录
                  └──────┬───────┘
                         ▼
        ┌────────────────┴────────────────┐
        │                                 │
   GroupFinder                       MessageFetcher
   (搜索/加入群)                     (历史 + 实时)
                                          │
                                          ▼
                                  list[MessageData]
                                          │
                                          ▼
                            KeywordFilter → LLMFilter
                                          │
                                          ▼
                                     Exporter
                                  (raw + filtered)
```

### 1. 登录 Telegram (TGClient)

`tg_intel_crawler/collector/client.py` 把 `TelegramClient` 封装成一个上下文管理器，自动处理首次登录、二步验证、`flood_sleep_threshold`：

```python
from tg_intel_crawler.collector.client import TGClient

async with TGClient("config/config.yaml") as tg:
    client = tg.client      # 拿到底层 Telethon TelegramClient
    me = await client.get_me()
```

- 首次登录：`send_code_request → input(code) → sign_in`，若开了二步验证再 `sign_in(password=...)`。
- 之后每次都是直接用本地的 `*.session` 文件登录，**不需要再次验证**。
- 内置 `flood_sleep_threshold = 60`：Telegram FloodWait < 60s 时 Telethon 会自动 sleep；大于 60s 才抛 `FloodWaitError`。

### 2. 发现群组 (GroupFinder)

`collector/group_finder.py` 调用 `contacts.SearchRequest` 按关键词搜索公开频道/群：

```python
from tg_intel_crawler.collector.group_finder import GroupFinder

finder = GroupFinder(client)
groups = await finder.search_groups(["抖音买号", "刷粉"], limit=20)
# [{"id": ..., "title": ..., "username": ..., "members_count": ..., "type": ...}]

await finder.join_group("douyinhao143")        # 也支持 https://t.me/xxx
```

CLI 入口：

```bash
tg-crawler discover --keywords "抖音买号,刷粉" --auto-join
# 不加 --auto-join 会提示交互选择，选中的群会被写入 config.yaml 的 groups 列表
```

### 3. 抓取消息 (MessageFetcher)

`collector/message_fetcher.py` 提供两种模式：

#### 历史消息

```python
from tg_intel_crawler.collector.message_fetcher import MessageFetcher
from tg_intel_crawler.utils.rate_limiter import RateLimiter

fetcher = MessageFetcher(client, RateLimiter(delay_min=2, delay_max=5))
messages = await fetcher.fetch_history("https://t.me/douyinhao143", days=7)
# messages: list[MessageData]
```

底层使用 `client.iter_messages(entity, offset_date=..., reverse=True)`，每爬 100 条调用一次 `RateLimiter.wait()` 做随机延迟（2~5 秒），命中 `FloodWaitError` 时 sleep 指定秒数。

`MessageData` 对原生消息做了归一化：

| 字段              | 含义                                    |
| ----------------- | --------------------------------------- |
| `msg_id`          | 消息 ID                                 |
| `group_id/name`   | 来源群 ID / 标题                        |
| `sender_id/name`  | 发送人 ID / 显示名                      |
| `sender_username` | @username                               |
| `text`            | 文本（空文本消息会被 `fetch_history` 跳过） |
| `date`            | UTC 时间                                |
| `media_type`      | `photo` / `document` / `video` / `None` |
| `forward_from`    | 转发来源（若有）                        |
| `reply_to`        | 引用消息 ID                             |

#### 实时监听

```python
async def on_new_message(msg: MessageData):
    print(msg.group_name, msg.text)

fetcher.start_realtime(groups=config["groups"], callback=on_new_message)
await client.run_until_disconnected()
```

内部基于 `@client.on(events.NewMessage(chats=groups))` 注册回调，只回调有文本的消息。

### 4. 抓取 Twitter (TwitterFetcher)

`collector/twitter_fetcher.py` 通过 `TwitterClient`（封装 [tikhub.io](https://tikhub.io)） 抓取：

- 关键词搜索：`fetcher.search(keyword, search_type="Latest", max_pages=5, days=7)`
- 用户时间线：`fetcher.user_tweets(screen_name="elonmusk", max_pages=5, days=7)`

CLI：

```bash
tg-crawler crawl-twitter --keywords "杀猪盘,刷单" --days 7
tg-crawler crawl-twitter --users "user1,user2"
# 不传参数则用 config.yaml 里的 twitter.search_keywords / monitor_users
```

返回的是 `TweetData`，与 `MessageData` 类似，最终都会被规范成统一的 `IntelRecord`（见下文）。

---

## 数据清洗流程

数据清洗分两级，先做廉价的关键词过滤把数据量降到 LLM 能承受的规模，再让 LLM 做语义判定。

### Step 1：关键词过滤 (KeywordFilter)

`filter/keyword_filter.py` 实现"产品词 ∩ 动作词"双命中：

```python
from tg_intel_crawler.filter.keyword_filter import KeywordFilter

kf = KeywordFilter("config/keywords.yaml")

kf.matches("出抖音老号实名号 联系tg@xxx")    # True (抖音 ∩ 老号)
kf.matches("今天天气真好")                    # False
kf.matches("抖音真好用")                      # False (没有动作词)

kf.get_matched_keywords("出抖音老号")
# {"products": ["抖音"], "actions": ["老号"]}
```

实现细节：
- 关键词通过 `re.escape + re.IGNORECASE` 编译为正则，支持中英混搭。
- 必须**同时**命中至少一个 product 和一个 action 才返回 True，可显著降低误报。

### Step 2：LLM 语义过滤 (LLMFilter)

`filter/llm_filter.py` 把命中关键词的消息批量丢给 LLM（默认火山方舟 Doubao，OpenAI 兼容协议）做判定：

```python
from tg_intel_crawler.filter.llm_filter import LLMFilter

llm = LLMFilter(config["llm"])
results = await llm.analyze([msg.text for msg in filtered_messages])
# results: list[AnalysisResult]
```

每条 `AnalysisResult` 字段：

| 字段          | 说明                                                 |
| ------------- | ---------------------------------------------------- |
| `is_relevant` | 是否真的与字节系黑灰产相关                           |
| `risk_type`   | 账号交易 / 刷量作弊 / 引流诈骗 / 数据泄露 / 工具交易 / 其他 |
| `risk_level`  | `high` / `medium` / `low`                            |
| `entities`    | `{accounts, contacts, links, tools, prices}`         |
| `summary`     | 一句话中文摘要                                       |

要点：
- 系统 prompt 见 `LLMFilter.SYSTEM_PROMPT`，强制 LLM 输出 JSON 数组（带 index）。
- `analyze()` 自动按 `batch_size`（默认 15）分批，避免单次 prompt 过长。
- 返回失败时会捕获 `JSONDecodeError` 并返回空列表（已记 log），不会让流水线挂掉。
- temperature 设为 0.1，输出更稳定。

> 想换模型？修改 `config.yaml` 的 `llm.base_url / model / api_key` 即可，只要兼容 OpenAI Chat Completions 协议（DeepSeek、通义、Moonshot、OpenAI 本身都行）。

---

## 数据保存 (Exporter)

`storage/exporter.py` 同时落多份：**SQLite 为主存储，JSON/CSV 双写兼容下游**。

```
output/
├── intel.db                                # ✅ 主存储：SQLite，按天分区
├── raw/                                    # 关键词过滤前的原始数据（JSON 兼容档案）
│   ├── 2026-05-25_群名A.json
│   └── twitter/
│       └── 2026-05-25_search_刷单.json
└── filtered/                               # LLM 命中后的结构化情报（JSON/CSV 兼容档案）
    ├── intel_2026-05-25.json               # Telegram
    ├── intel_2026-05-25.csv
    ├── intel_twitter_2026-05-25.json       # Twitter
    └── intel_twitter_2026-05-25.csv
```

### SQLite 主存储（`output/intel.db`）

为了解决"每天跑 `crawl` 导致 JSON 文件按天切片、跨天重复堆积"的问题，现在所有情报同时写入一个 SQLite 库，**每个数据源一对表 + `day` 分区列**。表名规则是 `<source>_intel_raw` / `<source>_intel_filtered`：

| 表 | 内容 | 主键（去重） |
|---|---|---|
| `telegram_intel_raw` | 关键词过滤前的原始消息（`payload` 存完整 JSON） | `(day, identity)`，identity = `msg_id`/`tweet_id` |
| `telegram_intel_filtered` | LLM 命中后的结构化情报（IntelRecord 展平） | `(day, id)` |

- **按天分区**：每条记录带 `day='2026-06-07'`，配 `idx_*_day` 索引，按天查询就是 `WHERE day = ?`。
- **去重语义**：联合主键 + `INSERT OR IGNORE` —— **同一天内重复跑不会重复入库**；**跨天则各存一份**（保留每天快照，便于做"某天新增了什么"的对比）。
- **多数据源扩展**：表名带数据源前缀，不同源**各存各的表、共用同一个 `intel.db`**。以后接入微博，只需 `Exporter(..., source="weibo")`（或 `SQLiteStore(db, source="weibo")`），就会自动建出 `weibo_intel_raw` / `weibo_intel_filtered`，逻辑完全复用。`source` 必须匹配 `[a-z][a-z0-9_]*`。
- **容错**：DB 写入失败不会影响已成功的 JSON/CSV 写入（双写互不阻塞）；构造 `Exporter(..., sqlite=False)` 可关闭 SQLite 回到纯文件模式。
- **旧表自动迁移**：早期版本用的是 `raw_messages` / `filtered_intel`（无数据源前缀）。新代码首次打开 DB 时会自动把它们的数据搬进 `telegram_intel_*` 并删除旧表，**数据零丢失、幂等**。

常用查询：

```bash
# 今天命中多少条 high 风险情报
sqlite3 output/intel.db \
  "SELECT COUNT(*) FROM telegram_intel_filtered WHERE day='2026-06-07' AND risk_level='high';"

# 按天看情报量
sqlite3 output/intel.db \
  "SELECT day, COUNT(*) FROM telegram_intel_filtered GROUP BY day ORDER BY day DESC;"

# 某群某天的原始消息条数
sqlite3 output/intel.db \
  "SELECT COUNT(*) FROM telegram_intel_raw WHERE day='2026-06-07' AND group_name='群名A';"
```

> 💡 JSON/CSV 仍按旧逻辑落盘（`raw` 文件内按 msg_id 去重，但文件名带日期、跨天不去重）。**想要"无跨天重复"的干净数据，查 `intel.db` 即可**；JSON/CSV 保留只为兼容已有的人工查阅/下游脚本。

两级写入分别由这两个方法负责：


```python
exporter = Exporter(output_dir="./output", formats=["json", "csv"])

# 1) 抓到原始消息后立即落盘（即使后面 LLM 失败也不丢数据）
exporter.export_raw(
    messages=[m.to_dict() for m in messages],
    group_name="群名A",
    subdir="",                # twitter 时传 "twitter"
)

# 2) LLM 命中的情报追加到当日合并文件
exporter.export_filtered(
    records=intel_records,    # list[IntelRecord]
    file_suffix="",           # twitter 时传 "twitter"
)
```

`IntelRecord` 是统一的情报结构，**Telegram 和 Twitter 共用**，靠 `source_platform` 字段区分：

```python
@dataclass
class IntelRecord:
    id: str                       # msg_<id> 或 tweet_<id>
    source_group: str             # 群名 / 关键词 / @user
    date: datetime
    sender_id: int
    sender_name: str
    sender_username: str
    original_text: str
    risk_type: str                # LLM 给出
    risk_level: str               # high/medium/low
    entities: dict                # {accounts, contacts, links, tools, prices}
    summary: str
    llm_model: str
    source_platform: str = "telegram"   # "telegram" | "twitter"
    source_url: str = ""
```

写盘细节：

- **JSON 增量合并**：当日文件已存在时先读出再 append，保证一天一文件不会被覆盖。
- **CSV 追加写**：用 `csv.DictWriter(quoting=QUOTE_ALL)` + `utf-8-sig`（Excel 友好），仅首次写表头。
- **`entities` 序列化**：CSV 里 entities 会被 `json.dumps`，避免逗号/换行污染列。
- **换行清理**：`original_text` 中的 `\n\r` 替换为空格，防止 CSV 断行。

---

## CLI 命令汇总

| 命令                                      | 作用                                          |
| ----------------------------------------- | --------------------------------------------- |
| `tg-crawler init`                         | 交互式写入 api_id / api_hash / phone          |
| `tg-crawler discover --keywords "a,b"`    | 按关键词搜索群组，可选 `--auto-join`（已限流） |
| `tg-crawler crawl --mode history --days 7`| 仅爬历史                                      |
| `tg-crawler crawl --mode realtime`        | 仅实时监听                                    |
| `tg-crawler crawl --mode both --days 7`   | 先回填历史再开实时（默认）                    |
| `tg-crawler crawl --include-joined`       | 把账号当前已加入的所有群一并爬一次            |
| `tg-crawler crawl --joined-only`          | 只爬已加入群，忽略 `config.groups`            |
| `tg-crawler crawl --exclude "@a,@b"`      | 临时排除某些群（精确 username/chat_id）       |
| `tg-crawler crawl-twitter --days 7`       | 爬 Twitter                                    |
| `tg-crawler crawl-bot`                    | 通过搜群 bot 按关键词检索情报（默认 @JISOU） |
| `tg-crawler groups list`                  | 列出已配置的群                                |
| `tg-crawler groups add <link>`            | 手动添加一个群                                |
| `tg-crawler groups list-joined`           | 列出账号当前已加入的群（不写盘）              |
| `tg-crawler groups sync`                  | 把已加入群合并到 `config.groups`              |
| `tg-crawler candidates list [--status …]` | 查看反向发现的群组候选池                      |
| `tg-crawler candidates approve <keys…>`   | 批准候选 → 限流加群 → 写入 `config.groups`    |
| `tg-crawler candidates reject <keys…>`    | 拒绝候选，永久不再出现在 pending             |
| `tg-crawler candidates stats`             | 候选池数量统计                                |
| `tg-crawler candidates verify`            | 校验 pending 候选实体类型，个人账号/机器人/无效的标记 rejected |
| `tg-crawler candidates llm-review`        | 用 LLM 自动审查 pending 候选，写 verdict + 可选加群     |
| `tg-crawler candidates llm-crawl`         | 让 LLM 从候选池挑群 → 加群 → 直接爬取数据落盘          |

### 群组自动扩展

爬虫会从抓到的每条消息里**反向挖出新群**（消息正文里的 `t.me/...` / `@username` / 转发来源），积累到 `config/discovered_groups.yaml`。你定期跑 `tg-crawler candidates list` 审一下，挑想加的批准、不想加的拒绝。

总共有三套用法，可以**单独使用，也可以叠在一起**。下面按"使用门槛从低到高"展开。

#### 用法 A：你手动加群，爬虫跟进（最简单）

适用场景：你比爬虫更懂"哪些群有价值"，所以**自己**在 Telegram 客户端里筛群、加群。爬虫只需要每次启动时问一下 Telegram："这个账号现在在哪些群？"然后把全部纳入爬取。

```bash
tg-crawler crawl --include-joined --days 7
```

它做的事：

1. 启动时调一次 `client.iter_dialogs()`，拿到账号当前所在的**所有**群和频道。
2. 与 `config.groups` 合并去重（同一个群只爬一次）。
3. 对合并后的列表逐个跑历史 + 实时（受 `--mode` 控制）。

参数细节：

| 选项 | 说明 |
|---|---|
| `--include-joined` | 把账号已加入群并入爬取目标。等价于在 `config.yaml#discovery.include_joined: true`，只是更显式。 |
| `--no-include-joined` | 显式关闭（用于覆盖 config 里设置的 `true`）。 |
| `--joined-only` | **只**爬已加入群，**忽略** `config.groups`。适合你完全靠手动加群、不维护 yaml 的场景。 |
| `--exclude "@a,@b,12345"` | 临时黑名单。可以是 `@username`、纯 username（不带 @），也可以是 chat_id 数字。 |
| `--days 7` | 历史回填范围。`--include-joined` 也会被这个参数限制。 |
| `--mode {history,realtime,both}` | 默认 `both`：先回填 N 天历史、再开实时监听。 |

典型输出：

```
📡 iter_dialogs: 23 joined groups/channels
... (开始按顺序爬每个群) ...
📥 Raw archive: +142 new (of 200 fetched)
🧭 Discovered 5 group signals (pool size now: 38)
Keyword filter: 12/200 messages passed
🤖 LLM analyzing 12 messages...
📊 Results: high=2, medium=3, low=1
```

> 💡 你今天用手机/客户端**手动**加了一个新群，今天跑 `--include-joined` 就能爬到，**不需要**改 yaml。

只想看看账号目前在哪些群（不爬数据）：

```bash
tg-crawler groups list-joined
# 输出每个群的标题、类型（group/supergroup/channel）、链接、成员数
```

---

#### 用法 B：让爬虫从消息里反向滚雪球（推荐主路径）

适用场景：你想让爬虫**自动**发现新群 —— 因为黑灰产群之间高频互导（"加 @xxx 进我的二群"、转发别的频道的内容），从已经在爬的消息里挖出"它们提到的别的群"，是非常高效的扩展方式。

正常跑 crawl，反向发现是**默认开启的**：

```bash
tg-crawler crawl --days 7
```

每爬完一个群，爬虫会：

1. 用 `GroupExtractor` 扫每条消息的 `text` / `entities` / `forward_from`，识别其中的 `t.me/...`、`@username`、`t.me/+invite_hash`、`t.me/joinchat/hash`。
2. 用严格的 TG 用户名规则过滤误报（`@中文` / `@1foo` / `@abc` 都不会被算作群名）。
3. 写入 `config/discovered_groups.yaml`，同名候选自动累加 `count`、合并 `sources`（最多保留首 3 条溯源）。

候选池长这样：

```yaml
candidates:
  douyinhao88:
    invite_hash: null
    first_seen: '2026-06-05T08:30:00+00:00'
    last_seen:  '2026-06-05T22:15:00+00:00'
    count: 7
    status: pending
    sources:
      - {group: 公群99, msg_id: 123456, channel: text}
      - {group: 抖音实名, msg_id: 789, channel: forward}
      - {group: 刷粉接单, msg_id: 4012, channel: text}
  '+abc123XYZ':
    invite_hash: abc123XYZ
    ...
```

接下来定期 review 候选池：

```bash
# 默认看 pending 的（高 count 排前面）
tg-crawler candidates list

# 也可以看其他状态
tg-crawler candidates list --status approved
tg-crawler candidates list --status rejected
tg-crawler candidates list --status all
```

输出例：

```
12 candidate(s) [pending]:

  douyinhao88                      count=7   status=pending  first=2026-06-05T08:30:00
  shuafentool                      count=5   status=pending  first=2026-06-04T17:11:00
  +abc123XYZ                       count=2   status=pending  first=2026-06-05T20:05:00
  ...
```

挑要加的群批准（用 list 里看到的 `key` 那一列，可以一次传多个）：

```bash
tg-crawler candidates approve douyinhao88 shuafentool +abc123XYZ
```

它做的事：

1. 把这些候选状态从 `pending` → `approved`。
2. 把对应的 `https://t.me/<key>`（私密群是 `https://t.me/+<hash>`）追加到 `config.groups`。
3. **限流加群** —— 走 `JoinThrottle`：
   - 默认每 30~90 秒加一个（随机间隔）。
   - 默认每天最多 20 个，超过会停下提示 "Daily join limit hit"，下次再跑会接着加。
   - 已经加过的群直接跳过、不占额度。
   - 命中 Telegram FloodWait 自动 sleep 后重试一次。

> ⚠️ **不要**调小 `min_interval` —— Telegram 的反作弊会盯单账号短时间内连续加群，几十秒内连加多个就可能被冻结。`30~90s` 已经是经验下限。

只想批准但不立刻加群（先排队，下次再加）：

```bash
tg-crawler candidates approve douyinhao88 --no-join
```

不想要的群直接拒：

```bash
tg-crawler candidates reject spamgrp adgrp
```

被拒绝的候选，**即使后面再次出现在消息里也不会复活**（保护机制：拒过一次就永远 reject）。

候选池统计：

```bash
tg-crawler candidates stats
#   approved   8
#   pending    23
#   rejected   5
#   total      36
```

#### 清理候选池里的个人账号/机器人（`candidates verify`）

候选是从消息正文用正则挖 `@username` 来的，而 Telegram 的用户名命名空间在**用户/机器人/群/频道之间共享** —— 所以池里难免混进"联系 @xz8568 买号"这类**个人账号**或机器人，它们根本不是群、没法爬。

`candidates verify` 对 pending 候选**逐个 `get_entity` 校验真实类型**，把个人账号、机器人、无法解析（已删/拼错/被封）的统统标记成 `rejected`，只把真正的群/频道留在 pending：

```bash
# 先试水：只看会把哪些判为非群组，不改状态
tg-crawler candidates verify --max 50 --dry-run

# 正式跑：默认校验 80 个高频候选（间隔 3s），非群组标记 rejected
tg-crawler candidates verify

# 候选多时分多次跑，每次 80 个；想更稳可再拉大间隔
tg-crawler candidates verify --max 80 --interval 5
```

要点：

- **私密 `+hash` 候选免校验**（邀请链接天然指向群，bot 也查不到）。
- 校验**高频候选优先**（按 `count` 排序），`--max` 截断单轮数量。
- **限流**：默认每个 `get_entity` 间隔 **3 秒**、单轮上限 **80** 个 —— 这是经验安全值。`get_entity` 解析陌生 username 是 Telegram 风控重点，**别一次校验太多、间隔别调太小**，否则会触发 FloodWait（动辄要求等几小时）。
- **FloodWait 自我保护**：万一还是撞上 FloodWait，命令会**主动停下**（不会傻等几小时），已校验的照常落盘，剩余的留在 pending 下次再跑。
- **判定规则**：group/channel → 保留；user/bot/not_found → `rejected`；其它短暂网络错误 → **保守保留**，下次再校验，不误杀。
- 被 reject 的候选**永久不再出现在 pending**，后续 `crawl` 即使再挖到也不会复活。

输出例：

```
🔬 Verifying 80 of 294 public pending candidate(s) (interval=3.0s)...
  ⨯ https://t.me/xz8568                     type=user
  ⨯ https://t.me/clhs9                      type=bot
  ⨯ https://t.me/deadname123                type=not_found
  ...
📊 Verify Summary
  Verified:   80 of 80 selected
  ✅ groups/channels kept: 38 (group=31, channel=7)
  ⨯ non-groups: 42 (user=20, bot=12, not_found=10)
  Rejected:   42 candidate(s) → status=rejected
```

> 💡 建议把它作为 `llm-review` / `llm-crawl` 的**前置清洗**：先 `verify` 把池里的账号/机器人筛掉，LLM 再审剩下的真群，既省 LLM 费用又更准。候选多时分多次跑（每次默认 80 个），跑完一轮再跑下一轮即可。

---

#### 用法 C：把已加入群一次性同步到配置（不爬）

适用场景：你想"快照式"地把账号当前所有群写进 `config.groups`，让 yaml 成为可见的可控清单 —— 之后 `tg-crawler crawl` 走 yaml 就够了，不用每次都依赖 `--include-joined` 实时拉。

```bash
tg-crawler groups sync
```

它做的事：

1. 跑一次 `iter_dialogs()` 列出账号当前已加入的群/频道。
2. 与 `config.groups` 合并去重。
3. 把新增的链接 append 进去，**不删除**原有条目（你以前手动写的 yaml 链接保留）。
4. 落盘 `config.yaml`，并打印新增了哪些。

输出例：

```
✅ Synced 5 new groups (total 28)
   + https://t.me/newgroup1
   + https://t.me/newgroup2
   ...
```

跑完一次 `sync` 后，正常 `tg-crawler crawl --days 7` 就会爬到这些群；以后不再用 `sync` 也行。

---

#### 三种用法的搭配

| 你想要的效果 | 推荐组合 |
|---|---|
| 一次性的小规模监控，群手动管 | 用法 C 一次 → 之后只用 `crawl` |
| 长期监控、爬虫自己滚雪球扩展 | 用法 B：日常 `crawl` + 周期性 `candidates approve` |
| 你高频在客户端里手动调整群列表，不想维护 yaml | 用法 A：每次 `crawl --include-joined`（或 yaml 里把 `discovery.include_joined: true` 设上） |
| 全开 | 三个一起用：`include_joined: true` + 反向发现自动开 + 定期 `candidates approve` |

#### 用法 D：让 LLM 自动审查候选池（替代手动 `candidates approve`）

当候选池长到几千条时，逐条 `candidates approve` 看不过来。`llm-review` 让 LLM 用两阶段方式批量初审：

1. **Stage 1（便宜）**：仅看候选 metadata（key、count、被哪些群传播、来源群历史信誉），批量过滤掉明显无关的（如"今日有羊毛🦙"群里偶尔被 mention 一次的私密群）。
2. **Stage 2（贵）**：对 Stage 1 通过的候选，从 `output/raw/` 拉来源消息原文，让 LLM 在真实上下文里判定是否高价值。

判决落到 yaml 里每个候选的 `llm_verdict` 字段，**不直接动 status**。要让 LLM 的 high/medium 判决真正写入 `config.groups`，需要显式 `--write-config`；要真正加群还需 `--auto-join`（仅对 high 生效，medium 只写 config 不加群）。

```bash
# 1. 试水：跑 50 条看看 LLM 选了啥（不写盘）
tg-crawler candidates llm-review --max-candidates 50 --dry-run

# 2. 正式跑一遍，写 verdict 到 yaml（不动 status）
tg-crawler candidates llm-review --max-candidates 200

# 3. 看 LLM 给了哪些 high
tg-crawler candidates list --status all --llm-verdict llm_approved_high

# 4. 觉得合理后落到 config.groups（仍不加群）
tg-crawler candidates llm-review --write-config

# 5. 真要自动加群：仅对 confidence=high 走 JoinThrottle (30~90s/个，daily_limit=20)
tg-crawler candidates llm-review --write-config --auto-join
```

关键约束：
- LLM 永远不写 `status: rejected`。被 LLM 否决的候选只是 verdict=`llm_rejected`，仍然留在 pending，你想推翻仍能手动 `candidates approve`。
- 重审增量：候选 `count` 翻倍 或 距上次 review 超 30 天，下次 `llm-review` 会自动重看（`--force-rereview` 可强制全部重审）。
- 私密群（`+hash`）置信度自动降一级；用 `--no-include-private` 可彻底跳过。
- `--auto-join` 必须配合 `--write-config`，否则报错（避免"加了群却没记 config"）。

#### 用法 E：让 LLM 选群并直接爬取（`llm-crawl`，一条龙）

`llm-review` 只"选群"不"爬数据"，选完还得再手动跑 `crawl`。`llm-crawl` 把两步合一：**让大模型在候选池里挑出合适的群组，立刻加群、爬取历史消息、跑完整 关键词→LLM→落盘 流水线**，并把爬过的群标记 approved、写入 `config.groups`。

```bash
# 1. 试水：让 LLM 看 50 个候选，挑出它认为合适的群（只看选了啥，不加群不爬）
tg-crawler candidates llm-crawl --max-candidates 50 --dry-run

# 2. 正式跑：LLM 选群 → 加群 → 爬最近 7 天 → 落盘情报（默认 confidence≥medium）
tg-crawler candidates llm-crawl --days 7

# 3. 只爬 LLM 高置信度的群，单轮最多爬 5 个
tg-crawler candidates llm-crawl --min-confidence high --max-crawl 5

# 4. 不加群，只爬已加入/可访问的群（更保守，避免触发反作弊）
tg-crawler candidates llm-crawl --no-join

# 5. 候选多、嫌慢？调高 Stage 2 并发（默认 5，注意 LLM 限速）
tg-crawler candidates llm-crawl --max-candidates 50 --stage2-concurrency 10 --dry-run
```

它做的事（`main.py:_candidates_llm_crawl_async`）：

1. 从候选池取 pending 候选，按 `count × 来源群情报信誉` 打分排序，取前 `--max-candidates`。
2. 跑两阶段 LLM 审查（与 `llm-review` 同一引擎 `CandidateReviewer`），写 `llm_verdict`。
3. 选出 confidence ≥ `--min-confidence` 的群（高置信度排前），最多取 `--max-crawl` 个。
4. **实体类型校验（在展示之前）**：LLM 只判断了"值不值得监控"，**它并不知道也无法判断候选是不是群组** —— 候选池里的 `@username` 是从消息正文挖的，而 Telegram 用户/机器人/群/频道**共用一套用户名**，像 `@xz8568`、`@clhs9` 这种很可能是黑灰产留的**联系人账号**而非群。所以连 TG 后先对每个公开候选做 `get_entity` 校验，把结果拆成两组：「✅ 已确认是群组」和「⨯ LLM 选中但非群组（已跳过）」，**只有确认是群/频道的才会进入后续加群/爬取**（私密 `+hash` 天然是群，免校验）。
5. 对每个校验通过的群：限流加群（`JoinThrottle`，30~90s/个、每天上限 20）→ `MessageFetcher.fetch_history(--days)` 爬历史 → 反向发现挖新候选 → 关键词过滤 → LLM 分析 → `Exporter` 落盘 `output/intel.db` + JSON/CSV。
6. 爬过的群标记 `status: approved` 并 append 到 `config.groups`（去重）。

各 flag：

| flag | 说明 | 默认 |
|---|---|---|
| `--max-candidates N` | 单轮喂给 LLM 审查的候选上限（按分数取 top-N） | 50 |
| `--stage2-concurrency N` | Stage 2 并发审查数（越大越快，但受 LLM 限速约束） | 5 |
| `--min-confidence {high,medium,low}` | 只爬 LLM 置信度不低于该级别的群 | medium |
| `--max-crawl N` | 单轮最多实际爬取多少个被选中的群 | 10 |
| `--days N` | 每个群回填多少天历史 | 7 |
| `--include-private/--no-include-private` | 是否纳入私密群（`+hash`，置信度自动降一级） | 包含 |
| `--no-join` | 跳过加群，只爬已加入/可访问的群 | 否（默认加群） |
| `--dry-run` | 只跑 LLM 选群，不加群、不爬取、不落盘 | 否 |

> ⚠️ `llm-crawl` 会**自动加群 + 自动爬取**，比 `llm-review` 更"激进"。建议先 `--dry-run` 看 LLM 选了哪些群，确认合理再正式跑。加群同样走 `JoinThrottle`（30~90s/个、daily_limit=20），命中上限会停下，剩余选中群保持 approved，下次接着爬。
>
> 💡 `--dry-run` 会跑 LLM 选群 **并连 TG 做实体类型校验**，输出和正式跑前半段一致（能看到哪些是真群、哪些是被识别出的个人账号/机器人），只是停在校验后、不加群/不爬取/不落盘。这样你 dry-run 时看到的「✅ 已确认群组」列表就是真群组，不会再把 `@xz8568` 这类账号误当成群。

输出例：

```
🔎 LLM reviewing 50 of 312 candidates (min-confidence=medium, max-crawl=10).

🤖 LLM selected 7 group(s) ≥ medium; crawling top 7:
  • douyinhao88                     confidence=high   账号交易 — 群名+来源高度疑似抖音账号交易
  • shuafentool                     confidence=medium 刷量作弊 — 来源群为已知刷量群
  ...
📡 Crawling douyinhao88 ...
📥 Raw archive: +142 new (of 200 fetched)
🤖 LLM analyzing 18 messages...
📊 Results: high=3, medium=5, low=2
...

📊 LLM Crawl Summary
  Groups crawled:     7
  Relevant records:   41 (high=12, medium=22, low=7)
  Approved + added to config.groups: 7
```

---

#### 微调参数（`config.yaml`）

```yaml
discovery:
  fetch_sender_bio: false      # 是否同时抽取发送者 bio 里的链接（默认关，避免烧 get_entity quota）
  candidates_path: ./config/discovered_groups.yaml
  include_joined: false        # crawl 默认是否并入已加群（CLI --include-joined 会覆盖）
  exclude_joined: []           # 永久黑名单
  scan_includes_channels: true # 频道是否纳入扫描（关掉只扫群）

join:
  min_interval: 30             # 加群最小间隔（秒）
  max_interval: 90
  daily_limit: 20              # 每天加群上限
  flood_retry: true            # FloodWait 自动重试一次
```

执行 `tg-crawler crawl` 的整条流水线（`main.py:_crawl_async`）：

1. 加载 `config.yaml` → 构造 `RateLimiter / KeywordFilter / LLMFilter / Exporter`
2. `async with TGClient(...)` 登录
3. 对每个群：
   1. `MessageFetcher.fetch_history(group, days)` → `list[MessageData]`
   2. `Exporter.export_raw(...)` 立即落原始数据
   3. `KeywordFilter.matches()` 一遍 → 留下命中的子集
   4. `LLMFilter.analyze()` 批量分析 → 留下 `is_relevant=True`
   5. 构造 `IntelRecord` → `Exporter.export_filtered(...)`
   6. 按 `risk_level` 统计 high/medium/low 打印日志
4. 若 mode 包含 realtime，注册 `start_realtime` 回调，每条新消息走"关键词→LLM→落盘"同样的链路，并 `client.run_until_disconnected()`。

---

## 通过搜群 bot 检索情报（`crawl-bot`）

适用场景：你想要**关键词级**的精准情报检索 —— 比如直接搜"抖加投流"、"实名号 出售"，让 `@JISOU` 这种搜群 bot 在它索引过的几百万消息里帮你找。

### 快速开始

确保 `config/config.yaml` 里有 `bot_search` 段（参考 `config.example.yaml`），然后挑一种用法跑：

```bash
# 默认：用 keywords.yaml 矩阵自动跑一轮，每条预览回访拿原文
tg-crawler crawl-bot

# 指定关键词
tg-crawler crawl-bot --keywords "抖加投流,实名号 出售"

# 不回访（只用预览片段）—— 更快，更安全（不被 TG 反爬识别）
tg-crawler crawl-bot --no-fetch-detail
```

### 完整用法

```bash
# 用法 1：默认 — 用 keywords.yaml 的 products × actions 矩阵自动跑一轮，
#         每条预览回访拿原文。最全面，最贴近真实情报。
tg-crawler crawl-bot

# 用法 2：指定关键词 — 只查你想要的，跳过自动矩阵。多个关键词用英文逗号分隔。
tg-crawler crawl-bot --keywords "抖加投流,实名号 出售,刷粉接单"

# 用法 3：跳过深链回访 — 更快、更安全（不向未加群发"游客式"请求），
#         代价：LLM 看到的是预览片段而不是原文，判断准确度下降。
#         适合：怕被反爬、只想看 bot 给的覆盖面、或前期试水。
tg-crawler crawl-bot --no-fetch-detail

# 用法 4：换 bot — 默认 @JISOU 失效或被封时，可换备用 bot。
#         也可以写进 config.yaml#bot_search.bots 列表自动 fallback。
tg-crawler crawl-bot --bot @SearchHubBot

# 用法 5：限制单轮 query 数 — 试水阶段先跑 5 个看看效果，再放开 max_queries。
tg-crawler crawl-bot --max-queries 5

# 用法 6（组合）：试水 — 5 个关键词、不回访、用备用 bot。
tg-crawler crawl-bot --bot @SearchHubBot --keywords "a,b,c,d,e" --no-fetch-detail
```

### 各 flag 详解

| flag | 说明 | 默认 |
|---|---|---|
| `--bot @xxx` | 强制使用某个 bot；覆盖 `config.yaml#bot_search.bots` 顺序 | `bot_search.bots[0]`（即 `@JISOU`） |
| `--keywords "a,b,c"` | 直接传查询词，**绕过** `keywords.yaml` 的 product × action 矩阵 | 不传 = 用 `keywords.yaml` 自动生成 |
| `--max-queries N` | 单轮最多发多少条 query | `bot_search.max_queries_per_run` (=30) |
| `--fetch-detail` | 强制开启回访（覆盖 config 的 `false`） | `bot_search.fetch_detail` (=`true`) |
| `--no-fetch-detail` | 强制关闭回访 | 同上 |

它做的事：

1. 启动时调 `client.get_entity(@JISOU)` 校验 bot 可达；不可达自动 fallback 到 `bot_search.bots` 列表里的下一个。
2. 用 `keywords.yaml` 自动拼 product × action 查询（如 `抖音 买号`、`字节 引流`），按 `bot_search.max_queries_per_run` 截断。
3. 每条 query 之间默认间隔 10 秒（`bot_search.query_interval_seconds`），避免 bot 反爬。
4. 把 bot 返回的每条结果按 emoji 切段，**广告行直接丢弃**（`广告:` / `广告：`）。
5. 全部预览片段先落 raw（`output/raw/bot/<date>_JISOU_<query>.json`） —— **即使 LLM 后面失败也不丢数据**。
6. 默认对每条带 `t.me/<channel>/<msg_id>` 的预览**回访拿原文**：
   - 公开群 → 直接 `get_messages` 拿全文 ✅
   - 私密但你已加 → 同上 ✅
   - 私密未加群 → 降级用预览片段，原文里加 `[preview-only]` 前缀提醒 LLM 保守判断
   - FloodWait 自动 sleep + 重试一次
7. 顺手把所有 t.me 链接送进**候选池**（和 `crawl` 反向发现共用一份 `discovered_groups.yaml`），等你 `candidates approve` 后限流加群。
8. 关键词预过滤 → LLM 分析 → 写入 `output/filtered/intel_bot_<date>.{json,csv}`，`source_platform="bot"`。

输出例：

```
🤖 crawl-bot: bot=@JISOU, queries=12, fetch_detail=True
Using bot: @JISOU
  keyword filter: 8/30 for query='抖音 买号'
  keyword filter: 5/22 for query='字节 引流'
  ...
✅ crawl-bot done. Saved 23 relevant records (high=8, medium=12, low=3)
   to ./output/filtered/intel_bot_*.
```

#### 微调参数（`config.yaml`）

```yaml
bot_search:
  enabled: false                            # 显式开关
  bots:
    - "@JISOU"                              # 优先；不可达 fallback 到下一个
  max_queries_per_run: 30
  query_interval_seconds: 10
  conversation_timeout_seconds: 15
  fetch_detail: true                        # 是否回访深链拿原文
  detail_max_per_query: 20                  # 单 query 最多回访 N 条
  detail_interval_seconds: 1                # 回访间隔
```

> ⚠️ **注意事项**
>
> - bot 寿命不稳定（被举报/被封会换名），半年后可能要换 `bots` 列表。当前 `@JISOU` 截图实测可用。
> - 默认开启 `fetch_detail` 会对每条预览发一次 `get_messages`，相当于"游客访问"行为。如果担心被 TG 反爬识别，可改 `--no-fetch-detail` 或 `fetch_detail: false`。
> - 同一 `<channel, msg_id>` 在多个 query 里出现会自动去重（`IntelRecord.id` 用 `bot_<channel>_<msg_id>` 作 key）。

---

## 候选群反查能力探测 (`probe-bot-lookup`)

`discovered_groups.yaml` 攒了几百上千个候选群后，下一步要让 LLM 来判定该不该爬。但 LLM 的输入材料取决于一个前提：搜群 bot（@JISOU 等）能反查到这些候选群多少？

`probe-bot-lookup` 用一次性诊断的方式回答这个问题：分层抽样 30 个候选 → 喂给 bot → 分类回复 → 输出 JSON + Markdown 报告。读-only，不改候选池状态。

```bash
# 默认：30 个候选，seed=42，输出到 output/probe/
tg-crawler probe-bot-lookup

# 小样本 smoke run
tg-crawler probe-bot-lookup --sample-size 6 --seed 1

# 切到别的 bot
tg-crawler probe-bot-lookup --bot @SomeOtherBot
```

报告里五种命中分类：

| 分类 | 含义 |
|---|---|
| `direct_hit` | bot 返回了该群本身的内容 |
| `indirect_hit` | bot 返回了 previews，但都不是该群（别人在讨论它）|
| `no_results` | bot 回复非空但解析不出 previews |
| `empty_reply` | bot 没回复 / 超时 |
| `error` | 其他异常 |

私密群（key 以 `+` 开头）天然只能落进后三档，因为 bot 索引不到 invite-only 群本身。

---

## 扩展与二次开发

| 想做的事                | 改哪里                                                                            |
| ----------------------- | --------------------------------------------------------------------------------- |
| 调整关键词维度          | `config/keywords.yaml` 的 `products` / `actions`                                  |
| 换 LLM / 换 prompt      | `config.yaml#llm` + `filter/llm_filter.py:LLMFilter.SYSTEM_PROMPT`                 |
| 改风险等级判定逻辑      | 同上 SYSTEM_PROMPT，注意保持 JSON 结构                                            |
| 加新输出格式（如 ES）   | 在 `storage/exporter.py` 加 `_write_es()` 等方法，并在 `export_filtered` 里调用   |
| 下载媒体                | `MessageFetcher.fetch_history` 里检测 `msg.media_type` 后 `await msg.download_media()` |
| 加新数据源（微博等）    | 仿照 `collector/twitter_*.py`，最终落到 `IntelRecord` 即可复用整套过滤/导出       |
| 调限流                  | `config.yaml#crawl.delay_min/max`                                                 |

### 直接当库用

如果不想走 CLI，可以把组件拆开当库用：

```python
import asyncio, yaml
from tg_intel_crawler.collector.client import TGClient
from tg_intel_crawler.collector.message_fetcher import MessageFetcher
from tg_intel_crawler.filter.keyword_filter import KeywordFilter
from tg_intel_crawler.filter.llm_filter import LLMFilter
from tg_intel_crawler.storage.exporter import Exporter, IntelRecord
from tg_intel_crawler.utils.rate_limiter import RateLimiter

async def main():
    cfg = yaml.safe_load(open("config/config.yaml"))
    kf  = KeywordFilter("config/keywords.yaml")
    llm = LLMFilter(cfg["llm"])
    exp = Exporter(cfg["output"]["dir"], cfg["output"]["format"])
    rl  = RateLimiter(cfg["crawl"]["delay_min"], cfg["crawl"]["delay_max"])

    async with TGClient("config/config.yaml") as tg:
        fetcher = MessageFetcher(tg.client, rl)
        msgs = await fetcher.fetch_history("https://t.me/your_group", days=3)

        exp.export_raw([m.to_dict() for m in msgs], group_name="your_group")

        hit = [m for m in msgs if kf.matches(m.text)]
        results = await llm.analyze([m.text for m in hit])

        records = [
            IntelRecord(
                id=f"msg_{m.msg_id}", source_group=m.group_name, date=m.date,
                sender_id=m.sender_id, sender_name=m.sender_name,
                sender_username=m.sender_username, original_text=m.text,
                risk_type=r.risk_type, risk_level=r.risk_level,
                entities=r.entities, summary=r.summary,
                llm_model=cfg["llm"]["model"],
            )
            for m, r in zip(hit, results) if r.is_relevant
        ]
        exp.export_filtered(records)

asyncio.run(main())
```

---

## 合规与风险提示

- 仅爬取**公开频道/群组**或你已加入并有权限的内容；不要碰需付费/邀请的私密群。
- 单账号大量请求会触发 Telegram FloodWait 甚至封号。`config.yaml#crawl.delay_min/max` 默认 2~5 秒，**不要调到 0**。
- LLM API 会把消息内容上传到第三方，注意敏感数据脱敏。
- 项目仅用于安全研究、风险监控等合法用途，使用者需自行遵守 [Telegram TOS](https://telegram.org/tos) 与所在地区法律。

---

## 测试

```bash
pip install -e ".[dev]"
pytest -q
```

---

## 贡献

欢迎以 Issue / PR 形式提改进建议。提交前请：

1. 确认 **没有把任何真实凭证**（api_id / api_hash / phone / api_key / `.session` 文件）放进改动里。
2. 跑一遍 `pytest`，至少不要让现有用例失败。
3. 如果新增依赖，请同时更新 `pyproject.toml` 与 `requirements.txt`。

## License

本项目采用 [MIT License](LICENSE) 发布。仅供学习、安全研究与风险监控等合法用途使用，使用者需自行承担相关法律与合规责任。
