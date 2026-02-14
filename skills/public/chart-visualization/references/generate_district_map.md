# generate_district_map — 行政区地图（中国）

## 功能概述
生成中国境内省/市/区/县的覆盖或热力图，可展示指标区间、类别或区域组成，适用于区域销售、政策覆盖等场景。

## 输入字段
### 必填
- `title`: string，必填且≤16 字，描述地图主题。
- `data`: object，必填，承载行政区配置及指标信息。
- `data.name`: string，必填，中国境内的行政区关键词，需明确到省/市/区/县。

### 可选
- `data.style.fillColor`: string，自定义无数据区域的填充色。
- `data.colors`: string[]，枚举或连续色带，默认提供 10 色列表。
- `data.dataType`: string，枚举 `number`/`enum`，决定颜色映射方式。
- `data.dataLabel`: string，指标名称（如 `GDP`）。
- `data.dataValue`: string，指标值或枚举标签。
- `data.dataValueUnit`: string，指标单位（如 `万亿`）。
- `data.showAllSubdistricts`: boolean，默认 `false`，是否展示全部下级行政区。
- `data.subdistricts[]`: array<object>，用于下钻各子区域，元素至少含 `name`，可附 `dataValue` 与 `style.fillColor`。
- `width`: number，默认 `1600`，设置图宽。
- `height`: number，默认 `1000`，设置图高。

## 使用建议
名称必须精确到行政层级，避免模糊词；若配置 `subdistricts`，需同时开启 `showAllSubdistricts`；地图只支持中国境内且依赖高德数据。

## 返回结果
- 返回地图图像 URL，并在 `_meta.spec` 中保留完整输入；若配置了 `SERVICE_ID`，生成记录会同步到“我的地图”小程序。