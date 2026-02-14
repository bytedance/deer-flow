# generate_histogram_chart — 直方图

## 功能概述
通过分箱显示连续数值的频数或概率分布，便于识别偏态、离群与集中区间。

## 输入字段
### 必填
- `data`: number[]，至少 1 条，用于构建频数分布。

### 可选
- `binNumber`: number，自定义分箱数量，未设置则自动估算。
- `style.backgroundColor`: string，设置背景色。
- `style.palette`: string[]，定义柱体颜色。
- `style.texture`: string，默认 `default`，可选 `default`/`rough`。
- `theme`: string，默认 `default`，可选 `default`/`academy`/`dark`。
- `width`: number，默认 `600`。
- `height`: number，默认 `400`。
- `title`: string，默认空字符串。
- `axisXTitle`: string，默认空字符串。
- `axisYTitle`: string，默认空字符串。

## 使用建议
清理空值/异常后再传入；样本量建议 ≥30；根据业务意义调整 `binNumber` 以兼顾细节与整体趋势。

## 返回结果
- 返回直方图 URL，并在 `_meta.spec` 存储参数。