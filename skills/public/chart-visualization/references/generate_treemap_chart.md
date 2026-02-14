# generate_treemap_chart — 矩形树图

## 功能概述
以嵌套矩形展示层级结构及各节点权重，适合资产占比、市场份额、目录容量等。

## 输入字段
### 必填
- `data`: array<object>，节点数组，每条含 `name`（string）与 `value`（number），可递归嵌套 `children`。

### 可选
- `style.backgroundColor`: string，设置背景色。
- `style.palette`: string[]，定义配色列表。
- `style.texture`: string，默认 `default`，可选 `default`/`rough`。
- `theme`: string，默认 `default`，可选 `default`/`academy`/`dark`。
- `width`: number，默认 `600`。
- `height`: number，默认 `400`。
- `title`: string，默认空字符串。

## 使用建议
确保每个节点 `value` ≥0，并与子节点之和一致；树层级不宜过深，可按需要提前聚合；为提升可读性可在节点名中加上数值单位。 

## 返回结果
- 返回矩形树图 URL，并同步 `_meta.spec`。