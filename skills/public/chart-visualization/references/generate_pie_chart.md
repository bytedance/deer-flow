# generate_pie_chart — 饼/环图

## 功能概述
展示整体与部分的占比，可通过内径形成环图，适用于市场份额、预算构成、用户群划分等。

## 输入字段
### 必填
- `data`: array<object>，每条记录包含 `category`（string）与 `value`（number）。

### 可选
- `innerRadius`: number，范围 [0, 1]，默认 `0`，设为 `0.6` 等值可生成环图。
- `style.backgroundColor`: string，设置背景色。
- `style.palette`: string[]，定义配色列表。
- `style.texture`: string，默认 `default`，可选 `default`/`rough`。
- `theme`: string，默认 `default`，可选 `default`/`academy`/`dark`。
- `width`: number，默认 `600`。
- `height`: number，默认 `400`。
- `title`: string，默认空字符串。

## 使用建议
类别数量建议 ≤6，若更多可聚合为“其它”；确保数值单位统一（百分比或绝对值），必要时在标题中说明基数。

## 返回结果
- 返回饼/环图 URL，并附 `_meta.spec`。