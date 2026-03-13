# generate_mind_map — 思维导图

## 功能概述
围绕中心主题展开 2~3 级分支，帮助组织想法、计划或知识结构，常用于头脑风暴、方案规划。

## 输入字段
### 必填
- `data`: object，必填，节点至少含 `name`，可通过 `children`（array<object>）递归扩展，建议深度 ≤3。

### 可选
- `style.texture`: string，默认 `default`，可选 `default`/`rough`。
- `theme`: string，默认 `default`，可选 `default`/`academy`/`dark`。
- `width`: number，默认 `600`。
- `height`: number，默认 `400`。

## 使用建议
中心节点写主题，一级分支代表主要维度（目标、资源、风险等），叶子节点使用短语；如分支较多，可先分拆多张导图。

## 返回结果
- 返回思维导图 URL，并在 `_meta.spec` 中保留节点树以便后续优化。