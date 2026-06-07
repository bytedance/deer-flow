# bot-search 集成（@JISOU 等搜群 bot）— 设计

| 字段 | 值 |
|---|---|
| 日期 | 2026-06-06 |
| 状态 | Draft → Approved |
| 上下文 | 现有 `crawl` 只能爬已加入群；`@JISOU` 这类搜群 bot 索引了远超单账号覆盖面的内容（截图："1,361,221 月活"），用它做关键词检索能精准定位到散落在私密/边缘群里的情报 |

## 目标

把搜群 bot（默认 `@JISOU`，可换）作为**第三种数据源**接入：

1. 用 `keywords.yaml` 的 products × actions 矩阵自动生成查询
2. 通过 Telethon `Conversation` API 和 bot 对话，拿到返回
3. **逐条回访拿原文**：bot 返回是预览片段，对每条深链 `https://t.me/<channel>/<msg_id>`：
   - 群是公开的 → `get_entity` + `get_messages` 拿**完整原文**
   - 群是私密但你已加 → 同上
   - 群是私密且你没加 → `ChannelPrivateError`，**降级**仅记预览 + 把 t.me 链接送进候选池
4. **双份持久化**：
   - **raw**：所有 bot 返回的预览片段（含降级未拿到原文的）落到 `output/raw/bot/`
   - **filtered**：拿到原文的走 KeywordFilter → LLMFilter，写入 `output/filtered/intel_bot_<date>.{json,csv}`
5. **顺手做候选池发现**：bot 返回里的 `t.me/<channel>` 链接全部进 `CandidatePool`，复用现有 review 流程

## 非目标（YAGNI）

- 不绕过 bot 反爬（不假装多账号、不脱身识别）
- 不主动加 bot 推荐的群（结果一律入候选池等人审）
- 不做"白名单频道列表"自动维护（DetailFetcher 每次都现查 entity 缓存）

## 模块划分

```
       ┌────────────────────────────────────┐
       │ keywords.yaml                      │
       │   products × actions               │
       └────────────────┬───────────────────┘
                        ▼
              ┌─────────────────────┐
              │ QueryGenerator      │   product × action 笛卡尔积
              │ - 上限 max_queries  │   + 临时 --keywords 覆盖
              └──────────┬──────────┘
                         ▼
              ┌─────────────────────┐
              │ BotQueryThrottle    │   每查询间隔 N 秒 + 单轮上限
              └──────────┬──────────┘
                         ▼
              ┌─────────────────────┐
              │ BotSearchClient     │   Telethon Conversation
              │ - send + get_response│   + 超时 + bot 不存在/封禁兜底
              └──────────┬──────────┘
                         ▼
              ┌─────────────────────┐
              │ BotResponseParser   │   按 emoji 起头切段
              │ - 产出 list[Preview]│   每条含 text / deeplink /
              │                     │   channel_username / msg_id
              └──────┬──────────────┘
                     │
        ┌────────────┼─────────────────┐
        ▼            ▼                 ▼
   raw 留底     候选池           DetailFetcher
   (export_raw) (GroupExtractor   对每条深链：
   subdir="bot") .extract_from_   - get_entity 缓存
                  text)           - get_messages(channel, msg_id)
                                  - 限流（独立 throttle）
                                  - 私密无权限 → 降级
                                          ▼
                              KeywordFilter → LLMFilter
                                          ▼
                                   IntelRecord(
                                     source_platform="bot",
                                     source_url=deeplink)
                                          ▼
                            export_filtered(file_suffix="bot")
```

## 数据结构

### `BotPreview`

```python
@dataclass
class BotPreview:
    bot: str                    # 哪个 bot 给的（@JISOU）
    query: str                  # 查询关键词
    raw_line: str               # bot 返回里这一行原始文本
    text: str                   # 解析出来的预览正文（可能被 fetch_detail 替换为原文）
    deeplink: str | None        # https://t.me/<channel>/<msg_id>，没有则 None
    channel_username: str | None
    msg_id: int | None
    icon: str | None            # 起头 emoji（可选，仅留作 debug）
    seen_at: datetime
    detail_fetched: bool = False  # 是否成功走过 fetch_detail
```

### bot 返回行的解析规则

经验观察：搜群 bot 返回的每条结果一行，常见两种格式：

```
🌄 X刀！香港1T_SSD大盘月付6.X元！_刚截获两份机密级套餐...
🎬 [00:09] 赏_好身材要不断雕刻_休闲穿搭女装_@抖加上热门dou+热点宝
```

切段规则（启发式，未必每个 bot 都完全一致 → 解析失败时整段当一条兜底）：

1. 按行 split
2. 行首是 emoji（`\p{Emoji}` 或我们维护的常见图标白名单）→ 一段开始
3. 段内可能含 `https://t.me/<channel>/<msg_id>`（提取） 或 `@username`
4. 解析失败的整段：text=整段、deeplink=None

### Bot 返回的"广告行"识别

截图最上面有一条`广告:南宫集团...`样式的行，需要过滤：

- 行首匹配 `^广告[:：]` → 标记 `is_ad=True`，**不进 raw、不进候选池、不进 LLM**
- 候补：包含明显博彩/赌博白名单关键词时也丢弃

## 关键决策

| 主题 | 决策 | 理由 |
|---|---|---|
| CLI 命名 | `tg-crawler crawl-bot` | 与 `crawl` / `crawl-twitter` 平行 |
| 默认 bot | `@JISOU` | 用户截图实测可用 |
| query 来源 | 默认 `keywords.yaml` 自动 product×action 矩阵 | 不忘扫面；`--keywords "a,b"` 临时覆盖 |
| query 上限 | `bot_search.max_queries_per_run: 30` | 单轮硬上限 |
| query 间隔 | 默认 10 秒 | bot 反爬保守值 |
| 默认 fetch detail | **开** | V1 走方案 B：bot 给的是预览，必须回访拿原文 |
| fetch detail 范围 | **公开 + 已加群**，私密未加群降级 | 实事求是：能拿就拿，拿不到记预览就好 |
| detail 限流 | 独立的 `DetailFetchThrottle`：每条 1 秒 + 单 query 上限 + FloodWait 自动 sleep | 拿原文是高频 API 调用，必须独立限流 |
| entity 缓存 | `dict[username → entity]`，单次 `crawl-bot` 内有效 | 同一 channel 多条深链复用 entity，省一半调用 |
| 关闭 detail 的开关 | `--no-fetch-detail` | 紧急排错或试水时跳过回访 |
| raw 落盘 | `output/raw/bot/<date>_<bot_name>_<safe_query>.json` | 与 twitter 的 `raw/twitter/` 同构；每个 query 一份方便 debug |
| filtered 落盘 | `output/filtered/intel_bot_<date>.{json,csv}` | 沿用 `Exporter.export_filtered(file_suffix="bot")` |
| `IntelRecord.id` | 优先 `bot_<channel>_<msg_id>`（拿到深链时），兜底 `bot_<bot>_<query_hash>_<line_idx>` | 前者天然去重，后者保唯一 |
| `IntelRecord.source_platform` | `"bot"` | 与 `"telegram"`/`"twitter"` 并列 |
| `IntelRecord.original_text` | 优先回访拿到的原文，降级时用预览片段 + 标记 `[preview-only]` | LLM 看到 `[preview-only]` 时知道判断要保守 |
| 候选池写入 | `channel="bot"` 标记 | `candidates list` 里能看出来源 |
| 广告行过滤 | 行首 `广告[:：]` 直接丢 | 简单可靠 |

## 配置新增

```yaml
bot_search:
  enabled: false                     # 没用到时显式关
  bots:
    - "@JISOU"                       # 主用 bot；可加多个，依次降级
  max_queries_per_run: 30
  query_interval_seconds: 10
  conversation_timeout_seconds: 15
  fetch_detail: true                 # 默认开（方案 B）；CLI --no-fetch-detail 可关
  detail_max_per_query: 20           # 每个 query 最多回访 N 条原文
  detail_interval_seconds: 1         # 回访间隔
```

## 错误与边界

| 场景 | 处理 |
|---|---|
| bot 不存在 / 名字写错 | 启动时 `client.get_entity(bot)` 一次，失败 → log + 跳过此 bot |
| bot 被你 block 了 | 一样会 get_entity 失败 |
| `Conversation` 超时（bot 没回） | 跳过该 query，记 log |
| bot 回了但全是广告 | 解析后所有 line 都被广告过滤 → 留空 raw 文件不写、log 提示 |
| FloodWait | 由 Telethon 自带 `flood_sleep_threshold=60` 处理；DetailFetcher 命中 ≥60s FloodWait 时 sleep + 重试一次 |
| `ChannelPrivateError` / `ChatAdminRequiredError` | 私密无权限 → 标 `detail_fetched=False`，回退预览文本 |
| `ValueError: Cannot find any entity ...` | bot 给了无效 channel 名 → 跳过 |
| LLM 分析失败 | 沿用 `Exporter.export_failed_batch` |
| 同一个深链在多个 query 里出现 | id 用 `bot_<channel>_<msg_id>` 时自动去重 |
| query 含特殊字符（"/"、空格） | filename 用 `re.sub(r'[^\w一-鿿]+', '_', query)` |
| 同一 channel 多条深链 | DetailFetcher 内部 `dict[username → entity]` 缓存，单次 crawl-bot 内有效 |

## 测试计划

| 模块 | 测试 |
|---|---|
| `BotResponseParser` | fixture：典型 bot 返回（含广告、emoji、深链、纯文本、空）→ 期望 BotPreview list；广告行被丢；解析失败兜底 |
| `BotQueryThrottle` | mock 时间，验证间隔 + 单轮上限；与 `JoinThrottle` 隔离 |
| `QueryGenerator` | 从 mock keywords.yaml 生成 product×action；`--keywords` 覆盖；上限截断 |
| `BotSearchClient` | mock Telethon `Conversation`；超时；bot 不存在；正常返回 |
| `DetailFetcher` | mock client.get_entity / get_messages；公开/已加群成功；`ChannelPrivateError` 降级；entity 缓存复用；FloodWait 重试 |
| `crawl-bot` 端到端 | mock client + 模拟 bot 响应；验证 raw/filtered 文件被写、候选池被增量；`--no-fetch-detail` 跳过回访路径 |

## 实施顺序

1. 设计文档 commit ✅
2. `BotResponseParser`（纯函数，最快）
3. `BotQueryThrottle`（mock 时间）
4. `QueryGenerator`（纯函数）
5. `BotSearchClient`（mock Conversation）
6. `DetailFetcher`（mock client + entity 缓存）
7. CLI `crawl-bot` 串联 raw → candidates → DetailFetcher → keyword → LLM → filtered
8. README 更新 + commit
