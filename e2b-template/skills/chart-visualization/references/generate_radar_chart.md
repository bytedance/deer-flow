# generate_radar_chart — 雷达图

## 功能概述
在多维坐标系上比较单个对象或多对象的能力维度，常用于评测、产品对比、绩效画像。

## 输入字段
### 必填
- `data`: array<object>，每条记录包含 `name`（string）与 `value`（number），可选 `group`（string）。

### 可选
- `style.backgroundColor`: string，设置背景色。
- `style.lineWidth`: number，设置雷达线宽。
- `style.palette`: string[]，定义系列颜色。
- `style.texture`: string，默认 `default`，可选 `default`/`rough`。
- `theme`: string，默认 `default`，可选 `default`/`academy`/`dark`。
- `width`: number，默认 `600`。
- `height`: number，默认 `400`。
- `title`: string，默认空字符串。

## 使用建议
维度数量控制在 4~8 之间；不同对象通过 `group` 区分并保证同一维度都给出数值；如量纲不同需先归一化。

## 返回结果
- 返回雷达图 URL，并附 `_meta.spec`。