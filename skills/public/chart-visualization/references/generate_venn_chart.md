# generate_venn_chart — 维恩图

## 功能概述
展示多个集合之间的交集、并集与差异，适用于市场细分、特性覆盖、用户重叠分析。

## 输入字段
### 必填
- `data`: array<object>，每条记录包含 `value`（number）与 `sets`（string[]），可选 `label`（string）。

### 可选
- `style.backgroundColor`: string，设置背景色。
- `style.palette`: string[]，定义配色列表。
- `style.texture`: string，默认 `default`，可选 `default`/`rough`。
- `theme`: string，默认 `default`，可选 `default`/`academy`/`dark`。
- `width`: number，默认 `600`。
- `height`: number，默认 `400`。
- `title`: string，默认空字符串。

## 使用建议
集合数量建议 ≤4；若缺少精确权重可根据大致占比填写；集合命名保持简洁明确（如“移动端用户”）。

## 返回结果
- 返回维恩图 URL，并保存在 `_meta.spec` 中。