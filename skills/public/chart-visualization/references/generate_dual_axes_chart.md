# generate_dual_axes_chart — 双轴图

## 功能概述
在同一画布上叠加柱状与折线（或两条不同量纲曲线），用于同时展示趋势与对比，如营收 vs 利润、温度 vs 降雨。

## 输入字段
### 必填
- `categories`: string[]，按顺序提供 X 轴刻度（如年份、月份、品类）。
- `series`: array<object>，每项至少包含 `type`（`column`/`line`）与 `data`（number[]，长度与 `categories` 一致），可选 `axisYTitle`（string）描述该系列 Y 轴含义。

### 可选
- `style.backgroundColor`: string，自定义背景色。
- `style.palette`: string[]，配置多系列配色。
- `style.texture`: string，默认 `default`，可选 `default`/`rough`。
- `theme`: string，默认 `default`，可选 `default`/`academy`/`dark`。
- `width`: number，默认 `600`。
- `height`: number，默认 `400`。
- `title`: string，默认空字符串。
- `axisXTitle`: string，默认空字符串。

## 使用建议
仅在确有不同量纲或图例对比需求时使用；保持系列数量 ≤2 以免阅读复杂；若两曲线差值巨大可使用次坐标轴进行缩放。 

## 返回结果
- 返回双轴图图像 URL，并随 `_meta.spec` 给出详细参数。