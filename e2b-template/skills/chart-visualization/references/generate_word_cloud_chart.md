# generate_word_cloud_chart — 词云图

## 功能概述
根据词频或权重调节文字大小与位置，用于快速提炼文本主题、情绪或关键词热点。

## 输入字段
### 必填
- `data`: array<object>，每条记录包含 `text`（string）与 `value`（number）。

### 可选
- `style.backgroundColor`: string，设置背景色。
- `style.palette`: string[]，定义词云配色。
- `style.texture`: string，默认 `default`，可选 `default`/`rough`。
- `theme`: string，默认 `default`，可选 `default`/`academy`/`dark`。
- `width`: number，默认 `600`。
- `height`: number，默认 `400`。
- `title`: string，默认空字符串。

## 使用建议
生成前去除停用词并合并同义词；统一大小写避免重复；如需突出情绪可按正负值映射配色。

## 返回结果
- 返回词云图 URL，并附 `_meta.spec`。