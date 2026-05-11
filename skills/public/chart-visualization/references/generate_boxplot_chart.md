# generate_boxplot_chart — 箱型图

## 功能概述
展示各类别数据的分布范围（最值、四分位、异常值），用于质量监控、实验结果或群体分布比较。

## 输入字段
### 必填
- `data`: array<object>，每条记录包含 `category`（string）与 `value`（number），可选 `group`（string）用于多组比较。

### 可选
- `style.backgroundColor`: string，设置背景色。
- `style.palette`: string[]，定义配色列表。
- `style.texture`: string，默认 `default`，可选 `default`/`rough`。
- `theme`: string，默认 `default`，可选 `default`/`academy`/`dark`。
- `width`: number，默认 `600`。
- `height`: number，默认 `400`。
- `title`: string，默认空字符串。
- `axisXTitle`: string，默认空字符串。
- `axisYTitle`: string，默认空字符串。

## 使用建议
单个类别至少提供 5 个样本以保证统计意义；如需展示多批次，可通过 `group` 或拆分多次调用。

## 返回结果
- 返回箱型图 URL，并在 `_meta.spec` 中储存输入规格。