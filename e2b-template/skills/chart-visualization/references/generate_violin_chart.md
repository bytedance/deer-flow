# generate_violin_chart — 小提琴图

## 功能概述
结合核密度曲线与箱型统计展示不同类别的分布形态，适合对比多批次实验或群体表现。

## 输入字段
### 必填
- `data`: array<object>，每条记录包含 `category`（string）与 `value`（number），可选 `group`（string）。

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
各类别样本量建议 ≥30 以确保密度估计稳定；如需要突出四分位信息，可与箱型图结合展示。

## 返回结果
- 返回小提琴图 URL，并在 `_meta.spec` 中保留配置。