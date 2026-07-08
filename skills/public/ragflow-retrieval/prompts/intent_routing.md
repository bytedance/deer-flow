# 知识库 + 部门 意图路由（Agent 专用）

> **性能提示**：默认不要走本文件的完整分步流程。优先用一键命令（见 `SKILL.md` §快速路径）：
>
> ```bash
> python /mnt/skills/public/ragflow-retrieval/scripts/route_intent.py query \
>   --question "{用户原问题}" --quiet \
>   --out /mnt/user-data/outputs/query.summary.json
> ```
>
> 仅当 `query` 返回 `ambiguous_intent` 或需手动指定 intent/部门时，再使用下方分步流程。

用户**不会**指定 dataset_id、知识库名称或部门。Agent 必须自动识别：

1. **哪个知识库**（信贷 / 制度）
2. **哪些部门**（top_k 个，可多选；仅对 `department_filter_enabled=true` 的库）

## 第一层：选知识库

| intent | 知识库 | 是否按部门过滤 |
|--------|--------|----------------|
| `信贷` | 信贷知识库 | ✅ 是（top 3 部门） |
| `制度` | 制度知识库 | ✅ 是（top 3 部门） |

判断规则见 `config/routing.json` 中每条 route 的 `description` / `keywords`。

## 第二层：选部门（信贷 / 制度均启用）

1. 读 `config/routing.json` → 当前 intent 的 `departments` 列表。
2. 根据用户问题语义，选出 **最多 top_k 个**相关部门（默认 3 个），不要只选 1 个。
3. **不要**单独跑 `score-departments`（慢）；直接在 `resolve` 或 `query` 里用 `--department-top-k 3` 或 `--departments`。

## 执行 resolve（写入 route.json + 部门 metadata 过滤）

向用户说明（≤100 字）：

```
📚 意图：{intent}（{label}）｜部门：{dept1、dept2、dept3 或「全库」} — {理由}
```

**方式 A — Agent 指定多个部门**：

```bash
python /mnt/skills/public/ragflow-retrieval/scripts/route_intent.py resolve \
  --intent "{intent}" \
  --question "{用户原问题}" \
  --departments "零售,对公,风控" \
  --out /mnt/user-data/outputs/route.json
```

**方式 B — 自动 keyword top_k（推荐，Agent 未把握部门时）**：

```bash
python /mnt/skills/public/ragflow-retrieval/scripts/route_intent.py resolve \
  --intent "{intent}" \
  --question "{用户原问题}" \
  --department-top-k 3 \
  --out /mnt/user-data/outputs/route.json
```

`route.json` → `filters.department_selection.selected_departments` 为最终部门；  
`filters.active_filter` 为运行时 metadata 条件（`部门 in [..]`），**禁止**让用户提供过滤 JSON。

## 检索

```bash
python /mnt/skills/public/ragflow-retrieval/scripts/ragflow_client.py run \
  --route /mnt/user-data/outputs/route.json \
  --question "{用户原问题}" \
  --quiet \
  --out /mnt/user-data/outputs/query.retrieval.json
```

## 边界情况

| 情况 | 行为 |
|------|------|
| `department_filter_enabled=false` 的库 | 不做部门过滤，全库检索 |
| 部门 keyword 全未命中 | 不做部门过滤，全库检索（`selection_method=none_matched`） |
| intent=ambiguous | 停止，请用户澄清信贷/制度 |
| RAGFlow 文档 metadata 字段 | 默认 `部门`，与 `routing.json` → `department_metadata_field` 一致 |

## 禁止

- 禁止问用户「哪个部门 / 过滤文件在哪」
- 禁止只选 1 个部门（除非 top_k=1 或仅 1 个部门命中 min_score）
- 禁止在已有 `query` 快速路径时仍分步 resolve + run + score-departments
