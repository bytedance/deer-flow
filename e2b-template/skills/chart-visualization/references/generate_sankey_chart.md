# generate_sankey_chart — 桑基图

## 功能概述
展示资源、能量或用户流在不同节点之间的流向与数量，适合预算分配、流量路径、能耗分布等。

## 输入字段
### 必填
- `data`: array<object>，每条记录包含 `source`（string）、`target`（string）与 `value`（number）。

### 可选
- `nodeAlign`: string，默认 `center`，可选 `left`/`right`/`justify`/`center`。
- `style.backgroundColor`: string，设置背景色。
- `style.palette`: string[]，定义节点配色。
- `style.texture`: string，默认 `default`，可选 `default`/`rough`。
- `theme`: string，默认 `default`，可选 `default`/`academy`/`dark`。
- `width`: number，默认 `600`。
- `height`: number，默认 `400`。
- `title`: string，默认空字符串。

## 使用建议
节点名称保持唯一，避免过多交叉；如存在环路需先打平为阶段流向；可按阈值过滤小流量以聚焦重点。

## 返回结果
- 返回桑基图 URL，并在 `_meta.spec` 存放节点与流量定义。