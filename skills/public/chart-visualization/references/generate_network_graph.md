# generate_network_graph — 网络关系图

## 功能概述
以节点与连线呈现实体之间的连接关系，适合社交网络、系统依赖、知识图谱等场景。

## 输入字段
### 必填
- `data`: object，必填，包含节点与连线。
- `data.nodes`: array<object>，至少 1 条，需提供唯一 `name`。
- `data.edges`: array<object>，至少 1 条，包含 `source` 与 `target`（string），可选 `name` 说明关系。

### 可选
- `style.texture`: string，默认 `default`，可选 `default`/`rough`。
- `theme`: string，默认 `default`，可选 `default`/`academy`/`dark`。
- `width`: number，默认 `600`。
- `height`: number，默认 `400`。

## 使用建议
节点数量保持在 10~50 之间以避免拥挤；确保 `edges` 中的 `source/target` 对应已存在的节点；可在 `label` 中注明关系含义。

## 返回结果
- 返回网络图 URL，并提供 `_meta.spec` 以便后续增删节点。