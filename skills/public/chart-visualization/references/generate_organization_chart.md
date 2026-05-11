# generate_organization_chart — 组织架构图

## 功能概述
展示公司、团队或项目的层级关系，并可在节点上描述角色职责。

## 输入字段
### 必填
- `data`: object，必填，节点至少含 `name`（string），可选 `description`（string），子节点通过 `children`（array<object>）嵌套，最大深度建议为 3。

### 可选
- `orient`: string，默认 `vertical`，可选 `horizontal`/`vertical`。
- `style.texture`: string，默认 `default`，可选 `default`/`rough`。
- `theme`: string，默认 `default`，可选 `default`/`academy`/`dark`。
- `width`: number，默认 `600`。
- `height`: number，默认 `400`。

## 使用建议
节点名称使用岗位/角色，`description` 简要说明职责或人数；若组织较大可拆分多个子图或按部门分批展示。

## 返回结果
- 返回组织架构图 URL，并在 `_meta.spec` 保存结构便于日后迭代。