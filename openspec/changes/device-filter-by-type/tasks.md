## 1. 类型定义与工具函数

- [ ] 1.1 `DeviceSelectorBlock` 的 props 接口增加 `filterDeviceType?: number` 字段
- [ ] 1.2 `DeviceSelectorMultiBlock` 的 props 接口增加 `filterDeviceType?: number` 字段
- [ ] 1.3 `collectDevices()` 函数签名增加可选的 `filterDeviceType?: number` 参数，当指定时仅收集 `type === filterDeviceType` 的设备

## 2. 组件层改造

- [ ] 2.1 `DeviceSelectorBlock` 从 `props.filterDeviceType` 读取参数并传入 `collectDevices()` 和 `useMemo` deps
- [ ] 2.2 `DeviceSelectorMultiBlock` 从 `props.filterDeviceType` 读取参数并传入 `collectDevices()` 和 `useMemo` deps

## 3. GenUI 基础设施

- [ ] 3.1 `sanitizer.ts` 白名单中为 `device-selector` 和 `device-selector-multi` 增加 `filterDeviceType`
- [ ] 3.2 `validator.ts` 中 `deviceSelectorPropsSchema` 和 `deviceSelectorMultiPropsSchema` 增加 `filterDeviceType: z.number().optional()` 字段

## 4. 调试面板 & 验证

- [ ] 4.1 `A2UIDebugPanel.tsx` 中为两个设备选择器组件增加 `filterDeviceType` 示例参数
- [ ] 4.2 运行 `pnpm check` 确保类型检查和 lint 通过
