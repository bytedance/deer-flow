## Context

当前 `DeviceSelectorBlock` 和 `DeviceSelectorMultiBlock` 的 `collectDevices()` 函数递归收集所有 `type < 10` 的设备节点（旋转机组=1、机泵=4、静设备=6、往复机组=9），不区分具体类型。后端 API `/api/organize/tree` 接受 `typeId` 参数可能进行服务端过滤，但前端侧无条件展示所有设备类型。

故障诊断 Agent 场景中，机泵诊断只需展示机泵（type=4），旋转机组诊断只需展示旋转机组（type=1）。当前依赖后端 `typeId` 过滤，缺少前端侧的明确保证。

## Goals / Non-Goals

**Goals:**
- `device-selector` 和 `device-selector-multi` 增加可选的 `filterDeviceType: number` props 参数
- 当指定时，`collectDevices()` 仅收集 `type === filterDeviceType` 的设备
- 未指定时行为不变，保持向后兼容
- 更新 sanitizer 白名单和 Zod schema 以允许新参数

**Non-Goals:**
- 不在 UI 上增加用户可操作的设备类型筛选控件（下拉框、Tab 等）
- 不修改后端 API 或 Agent SOUL 文件
- 不支持多类型同时过滤（如同时显示机泵+旋转机组）
- 不移除已有的 `queryParams.typeId`（两者独立工作，互不干扰）

## Decisions

### 1. `filterDeviceType` 作为顶层 props 而非嵌套在 `queryParams` 中

**选择**: `props.filterDeviceType`（与 `title`、`maxSelect` 同级）

**理由**: `queryParams` 的职责是传递给后端 API 的查询参数（userId、orgId、treeType、typeId）。`filterDeviceType` 是纯前端行为——控制 `collectDevices()` 的过滤逻辑，不发送给 API。放在顶层语义更清晰。

**替代方案**: 复用 `queryParams.typeId` 在前端做过滤。被拒绝，因为 `typeId` 已在 API 请求中使用，混淆其职责。

### 2. 过滤发生在 `collectDevices()` 中

**选择**: 修改 `collectDevices(node, filterDeviceType?)` 签名，增加可选的类型过滤参数。

**理由**: `collectDevices` 是唯一负责从组织树中提取设备列表的函数，过滤逻辑集中在此处最简洁。两个组件各自调用时传入 `filterDeviceType`。

### 3. 设备类型常量复用现有定义

**选择**: 复用 `DEVICE_TYPE_LABELS` 中已定义的设备类型（1、4、6、9），不做额外验证。传入不在范围内的值（如 99）时，`collectDevices` 返回空列表。

**理由**: 设备类型定义已存在且稳定。无需引入额外的枚举校验，由 Zod schema 的 `z.number().optional()` 保证类型正确性。

## Risks / Trade-offs

- **Agent 传错 `filterDeviceType` 导致无设备展示** → 属于 Agent 配置问题，与传错 `typeId` 同等性质。组件不做额外校验，展示"该组织节点下无设备"即可
- **`filterDeviceType` 与 `queryParams.typeId` 同时使用时行为叠加** → 文档明确说明两者独立：`typeId` 影响 API 返回，`filterDeviceType` 在前端二次过滤。通常只需使用其中一个
