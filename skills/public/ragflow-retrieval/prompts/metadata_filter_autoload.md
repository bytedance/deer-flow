# 元数据过滤自动加载（Agent 必读）

部门 metadata 过滤由 **`route_intent.py resolve` 自动生成**，写入 `route.json` → `filters.active_filter`。

## 过滤生成规则

| 选中部门数 | meta_data_filter 形状 |
|-----------|----------------------|
| 1 个 | `{"key":"部门","op":"=","value":"零售金融部"}` |
| 多个 | `{"key":"部门","op":"in","value":["零售金融部","对公业务部",...]}` |

RAGFlow 文档 metadata 字段名默认 **`部门`**（可在 `routing.json` 修改 `department_metadata_field`）。

## Agent 不要做的事

- 不要手动编辑 `config/filters/*.json` 来填部门（运行时 filter 优先）
- 不要让用户提供过滤 JSON 路径
- 不要跳过 `resolve` 直接 `retrieve`

## 运维配置（一次性）

1. 给 RAGFlow 文档写入 metadata：`{"部门": "零售金融部"}`
2. 编辑 `config/routing.json`：
   - 各 intent 的 `dataset_id`
   - `departments` 列表（id / label / metadata_value / keywords）— **信贷与制度各自独立维护**
   - `department_filter_enabled`：当前信贷、制度均为 `true`
   - `department_top_k`：默认 3

## debug

```bash
python /mnt/skills/public/ragflow-retrieval/scripts/route_intent.py list-filters
python /mnt/skills/public/ragflow-retrieval/scripts/route_intent.py list-routes
```
