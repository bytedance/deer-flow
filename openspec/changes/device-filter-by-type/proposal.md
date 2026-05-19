## Why

当前设备选择器组件在前端侧收集所有 `type < 10` 的设备节点，无法按具体设备类型（旋转机组=1、机泵=4、静设备=6、往复机组=9）进行过滤。故障诊断 Agent（机泵/旋转/往复）需要在选择器中仅展示对应类型的设备，但目前仅依赖后端 API 的 `typeId` 参数，缺少前端侧的保证。增加 `filterDeviceType` 参数让 Agent 可以明确指定组件只展示某一类设备。

## What Changes

- `device-selector` 和 `device-selector-multi` 组件增加 `filterDeviceType` props 参数（数字类型，可选）
- 当 `filterDeviceType` 指定时，`collectDevices()` 仅收集匹配该类型的设备节点
- 更新 `DeviceSelectorBlockProps` 和 `DeviceSelectorMultiBlockProps` 类型定义
- 更新 sanitizer 白名单，将 `filterDeviceType` 加入两个组件的允许 props
- 更新 Zod 校验 schema，为两个组件的 props schema 增加 `filterDeviceType` 字段
- 更新调试面板中两个组件的默认 props 示例

## Capabilities

### Modified Capabilities
- `a2ui-device-selector`: 新增 `filterDeviceType` 参数，组件按设备类型过滤右侧设备列表；单选和多选组件均适用

## Impact

- 前端组件: `DeviceSelectorBlock.tsx`, `DeviceSelectorMultiBlock.tsx`, `device-selector-types.ts`
- GenUI 核心: `sanitizer.ts`, `validator.ts`
- 调试面板: `A2UIDebugPanel.tsx`
- 不影响后端 API、Agent SOUL 文件（已有 Agent 通过 `typeId` 传参，后续可改用 `filterDeviceType` 获得前端侧保证）
- 非破坏性变更：新参数可选，未指定时行为不变
