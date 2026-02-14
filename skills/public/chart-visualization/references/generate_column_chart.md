# generate_column_chart — 柱状图

## 功能概述
纵向柱状对比不同类别或时间段的指标，可分组或堆叠展示，常用于销量、营收、客流对比。

## 输入字段
### 必填
- `data`: array<object>，每条至少含 `category`（string）与 `value`（number），如需分组或堆叠需补充 `group`（string）。

### 可选
- `group`: boolean，默认 `true`，用于按系列并排展示不同 `group`，开启时需确保 `stack=false` 且数据包含 `group`。
- `stack`: boolean，默认 `false`，用于将不同 `group` 堆叠到同一柱子，开启时需确保 `group=false` 且数据包含 `group`。
- `style.backgroundColor`: string，自定义背景色。
- `style.palette`: string[]，定义配色列表。
- `style.texture`: string，默认 `default`，可选 `default`/`rough`。
- `theme`: string，默认 `default`，可选 `default`/`academy`/`dark`。
- `width`: number，默认 `600`。
- `height`: number，默认 `400`。
- `title`: string，默认空字符串。
- `axisXTitle`: string，默认空字符串。
- `axisYTitle`: string，默认空字符串。

## 使用建议
当类别较多（>12）时可按 Top-N 或聚合；堆叠模式要确保各记录都含 `group` 字段以免校验失败。

## 返回结果
- 返回柱状图 URL，并随 `_meta.spec` 提供配置详情。