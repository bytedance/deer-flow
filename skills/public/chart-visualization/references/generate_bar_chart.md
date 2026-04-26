# generate_bar_chart — 条形图

## 功能概述
以横向条形比较不同类别或分组的指标表现，适合 Top-N 排行、不同地区或渠道对比。

## 输入字段
### 必填
- `data`: array<object>，每条至少含 `category`（string）与 `value`（number），如需分组或堆叠需额外提供 `group`（string）。

### 可选
- `group`: boolean，默认 `false`，启用后以并排形式展示不同 `group`，并要求 `stack=false` 且数据含 `group` 字段。
- `stack`: boolean，默认 `true`，启用后将不同 `group` 堆叠在同一条形上，并要求 `group=false` 且数据含 `group` 字段。
- `style.backgroundColor`: string，自定义背景色（如 `#fff`）。
- `style.palette`: string[]，设置系列颜色列表。
- `style.texture`: string，默认 `default`，可选 `default`/`rough`。
- `theme`: string，默认 `default`，可选 `default`/`academy`/`dark`。
- `width`: number，默认 `600`，控制图表宽度。
- `height`: number，默认 `400`，控制图表高度。
- `title`: string，默认空字符串，用于设置图表标题。
- `axisXTitle`: string，默认空字符串，设置 X 轴标题。
- `axisYTitle`: string，默认空字符串，设置 Y 轴标题。

## 使用建议
类别名称保持简短；若系列数较多可改用堆叠或筛选重点项目，以免图表拥挤。

## 返回结果
- 返回条形图图像 URL，并在 `_meta.spec` 中给出完整配置以便复用。