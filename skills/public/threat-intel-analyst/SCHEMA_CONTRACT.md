# 情报库 Schema 契约（多数据源协作规范）

> 给「各自维护独立数据源」的队友。只要你的 SQLite 库符合本契约，
> 就能被 `IntelFederation` 联邦查询层统一聚合，无需改任何查询代码。

## 一、总原则

- **每个数据源一个独立 SQLite 库**（你自己维护，路径自定）。
- 库内表名带**数据源前缀**：`<source>_intel_filtered` / `<source>_intel_raw`。
  - `source` 必须匹配 `^[a-z][a-z0-9_]*$`，如 `weibo` / `forum` / `darkweb`。
- 把库注册进 `_shared/federation.yaml` 即可被联邦查询。

## 二、表结构（必须一致）

### `<source>_intel_filtered`（结构化情报，分析层查这张）

| 列 | 类型 | 说明 | 必填 |
|---|---|---|---|
| `day` | TEXT | 分区日 `YYYY-MM-DD` | ✅ |
| `id` | TEXT | 该源内唯一记录 id（如 `weibo_<mid>`） | ✅ |
| `source_platform` | TEXT | 来源标识：`weibo`/`forum`/... | ✅ |
| `source_group` | TEXT | 来源群/版块/话题名 | |
| `msg_date` | TEXT | 原始消息时间(isoformat) | |
| `sender_id` | INTEGER | 发送者 id | |
| `sender_name` | TEXT | 发送者名 | |
| `sender_username` | TEXT | 发送者 @ | |
| `original_text` | TEXT | 原文 | |
| `risk_type` | TEXT | 账号交易/刷量作弊/引流诈骗/数据泄露/工具交易/其他 | ✅ |
| `risk_level` | TEXT | `high`/`medium`/`low` | ✅ |
| `entities` | TEXT | **JSON 字符串**：`{accounts,contacts,links,tools,prices}`，各源特有字段也塞这里 | ✅ |
| `summary` | TEXT | 一句话摘要 | |
| `llm_model` | TEXT | 判定模型 | |
| `source_url` | TEXT | 原文链接 | |
| `suffix` | TEXT | 子类标签(可空) | |
| `inserted_at` | TEXT | 入库时间 | |

主键：`PRIMARY KEY (day, id)`（同天去重、跨天各存一份）。
建议索引：`day` / `risk_level` / `source_platform`。

### `<source>_intel_raw`（原始归档，可选）

`day, identity, group_name, subdir, msg_date, payload(JSON), inserted_at`，
主键 `(day, identity)`。

## 三、最省事的入库方式：复用 SQLiteStore

底层项目已提供通用写入器，直接 `source=` 即可生成你的表，schema 自动正确：

```python
from tg_intel_crawler.storage.sqlite_store import SQLiteStore

store = SQLiteStore("/your/path/weibo.db", source="weibo")
# filtered（IntelRecord-as-dict，date 用 isoformat，entities 可为 dict 或 JSON 串）
store.insert_filtered([{
    "id": "weibo_4998",
    "date": "2026-06-07T10:00:00",
    "source_platform": "weibo",
    "source_group": "某超话",
    "original_text": "...",
    "risk_type": "刷量作弊",
    "risk_level": "high",
    "entities": {"contacts": ["wx:xxx"], "prices": ["50元"]},
    "summary": "刷阅读量",
    "llm_model": "your-model",
}], day="2026-06-07")
# raw（可选）
store.insert_raw([{"msg_id": 4998, "text": "..."}], group_name="某超话", day="2026-06-07")
```

> 这样写出来的 `weibo_intel_filtered` / `weibo_intel_raw` 与本契约完全一致，
> `(day,id)` 去重、按天分区都已内置。

## 四、注册到联邦查询

在 `_shared/federation.yaml` 增加你的库：

```yaml
databases:
  - alias: weibo
    path: /abs/path/to/weibo.db   # 绝对路径或相对本 yaml
    owner: teammateA
```

完成后，`threat-intel-analyst` 的 `trends/top_groups/top_entities/keyword_heat/
generate_report/query_intel` 会**自动把你的数据纳入**，可用 `source_platform=weibo`
单独看你的源，也可不加过滤跨源聚合。

## 五、约束

- `entities` 必须是合法 JSON 字符串（或写入时传 dict，SQLiteStore 会自动序列化）。
- `risk_level` 只用 `high/medium/low`；`risk_type` 尽量用上面 6 类，便于跨源聚合。
- 联邦层以 **只读(ro)** 方式 attach 各库，不会改你的数据；库缺失/锁定会被跳过而非报错。
- 各源库**互不写入对方**——你只管自己的库，聚合在查询时发生。
