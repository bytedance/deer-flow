# generate_funnel_chart — 漏斗图

## 功能概述
展示多阶段转化或流失情况，常用于销售管道、用户旅程等逐步筛选过程。

## 输入字段
### 必填
- `data`: array<object>，需按流程顺序排列，每条包含 `category`（string）与 `value`（number）。

### 可选
- `style.backgroundColor`: string，设置背景色。
- `style.palette`: string[]，定义各阶段颜色。
- `style.texture`: string，默认 `default`，可选 `default`/`rough`。
- `theme`: string，默认 `default`，可选 `default`/`academy`/`dark`。
- `width`: number，默认 `600`。
- `height`: number，默认 `400`。
- `title`: string，默认空字符串。

## 使用建议
阶段顺序需按实际流程排列；若数值为百分比应统一基准并在标题或备注中说明口径；避免阶段过多导致阅读困难（建议 ≤6）。

## 返回结果
- 返回漏斗图 URL，并附 `_meta.spec` 方便复用。