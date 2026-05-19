## Why

当前设备选择器组件仅支持选择顶层设备（旋转机组、机泵、往复机等），但工业诊断场景中需要进一步选择设备下的部件/子设备（如旋转机组下的测点、机泵下的轴承等）。缺少子设备选择能力导致 Agent 无法精确指定诊断目标，需要新增一个子设备选择 A2UI 交互组件。

## What Changes

- 新增 `sub-device-selector` A2UI 交互组件，包含内置的单选设备选择器用于确定父设备
- 通过父设备选择触发 RPC 调用 `ins-bus-rpc/getComponentInfoByMachineId`，获取该设备下的子设备列表
- 根据父设备类型自动过滤子设备：旋转机组（type=1）过滤子设备 type=80，机泵（type=4）过滤子设备 type=50，往复机（type=9）过滤子设备 type=100 或 110
- 新增后端 RPC 客户端封装 `getComponentInfoByMachineId` 调用
- 新增 Gateway 代理端点 `/api/machine/component-info` 供前端调用
- 在组件注册表、属性清理器、属性验证器中注册新组件

## Capabilities

### New Capabilities
- `a2ui-sub-device-selector`: 子设备选择 A2UI 交互组件，包含父设备单选和子设备列表展示，支持按父设备类型自动过滤子设备类型

### Modified Capabilities
<!-- No existing specs have requirement changes. This is purely additive. -->

## Impact

- 前端 `frontend/src/components/genui/`：新增 `SubDeviceSelectorBlock.tsx`
- 前端 `frontend/src/core/genui/`：registry.ts、sanitizer.ts、validator.ts 增加新组件条目
- 后端 `backend/packages/harness/deerflow/rpc/`：新增或扩展 RPC 客户端（machine_service.py 增加 getComponentInfoByMachineId 方法）
- 后端 `backend/app/gateway/routers/`：新增 `/api/machine/component-info` 代理端点
- 后端 `backend/app/gateway/app.py`：注册新路由
