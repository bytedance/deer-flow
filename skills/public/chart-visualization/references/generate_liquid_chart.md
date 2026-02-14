# generate_liquid_chart — 水波图

## 功能概述
以液面高度展示单一百分比或进度，视觉动效强，适合达成率、资源占用等指标。

## 输入字段
### 必填
- `percent`: number，取值范围 [0,1]，表示当前百分比或进度。

### 可选
- `shape`: string，默认 `circle`，可选 `circle`/`rect`/`pin`/`triangle`。
- `style.backgroundColor`: string，自定义背景色。
- `style.color`: string，自定义水波颜色。
- `style.texture`: string，默认 `default`，可选 `default`/`rough`。
- `theme`: string，默认 `default`，可选 `default`/`academy`/`dark`。
- `width`: number，默认 `600`。
- `height`: number，默认 `400`。
- `title`: string，默认空字符串。

## 使用建议
确保百分比经过归一化；单图仅支持一个进度，如需多指标请并排生成多个水波图；标题可写“目标完成率 85%”。

## 返回结果
- 返回水波图 URL，并在 `_meta.spec` 中记录参数。