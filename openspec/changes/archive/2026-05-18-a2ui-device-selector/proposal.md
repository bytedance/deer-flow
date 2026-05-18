## Why

当前 A2UI 组件库缺少设备选择能力，用户在对话中无法直观地从组织设备树中勾选设备（旋转机组、机泵、静设备、往复机组）。需要新增设备选择器组件，支持单选和多选两种模式，供 Agent 在需要用户指定设备范围时动态下发。

## What Changes

- 新增 A2UI 组件 `device-selector`（设备单选选择器），左右分栏布局：左侧可折叠组织树展示 type>=10 的组织节点，右侧展示选中组织节点下的 type<10 设备列表，点击设备即选中回传
- 新增 A2UI 组件 `device-selector-multi`（设备多选选择器），与单选布局一致，右侧支持复选框多选 + 提交按钮回传
- 新增后端 RPC 客户端 `OrganizeServiceClient`，封装 `ins-bus-rpc` 服务的 `/organize/getOrgTreeByUserIdAndOrgId` 接口
- 组件默认入参：userId=1, orgId=0, treeType=1
- 在 registry.ts / sanitizer.ts / validator.ts 中注册新组件

## Capabilities

### New Capabilities

- `a2ui-device-selector`: 设备选择器组件，包含单选和多选两个变体。通过调用 ins-bus-rpc 组织树接口获取设备树数据，以树形选择器展示，过滤仅可选 type<10 的节点（旋转机组 type=1、机泵 type=4、静设备 type=6、往复机组 type=9），type>=10 为组织节点不可选。

### Modified Capabilities

<!-- 无现有能力的需求变更 -->

## Impact

- 前端新增组件文件 `frontend/src/components/genui/DeviceSelectorBlock.tsx`、`DeviceSelectorMultiBlock.tsx`
- 修改 `frontend/src/core/genui/registry.ts`：注册 2 个新组件
- 修改 `frontend/src/core/genui/sanitizer.ts`：添加新组件的 props 白名单
- 修改 `frontend/src/core/genui/validator.ts`：添加新组件的 Zod schema
- 后端新增 `backend/packages/harness/deerflow/rpc/organize_service.py`：封装组织树 API
- 依赖 `ins-bus-rpc` 服务的 `/organize/getOrgTreeByUserIdAndOrgId` 接口
- 前端新增自定义可折叠树组件（纯 Tailwind 实现，零外部依赖）
