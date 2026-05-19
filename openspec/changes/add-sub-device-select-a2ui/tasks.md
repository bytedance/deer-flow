## 1. 后端 RPC 客户端

- [x] 1.1 在 `MachineServiceClient` 中新增 `get_component_info_by_machine_id(machine_id, hidden_if_valid)` 方法，调用 `ins-bus-rpc /getComponentInfoByMachineId` GET 端点，使用 `_unwrap_ajax_result` 解包返回

## 2. 后端 Gateway 代理端点

- [x] 2.1 创建 `backend/app/gateway/routers/machine.py`，注册 `/api/machine` 前缀路由，实现 `GET /component-info` 端点（接受 machineId 必填、hiddenIfValid 可选参数），代理到 `MachineServiceClient.get_component_info_by_machine_id()`
- [x] 2.2 在 `backend/app/gateway/app.py` 中 `include_router(machine.router)`

## 3. 前端核心注册

- [x] 3.1 在 `frontend/src/core/genui/registry.ts` 的 `COMPONENT_REGISTRY` 中注册 `sub-device-selector`，懒加载指向 `@/components/genui/SubDeviceSelectorBlock`
- [x] 3.2 在 `frontend/src/core/genui/sanitizer.ts` 的 `ALLOWED_PROPS_BY_COMPONENT` 中为 `sub-device-selector` 添加白名单 `["title", "queryParams"]`
- [x] 3.3 在 `frontend/src/core/genui/validator.ts` 中为 `sub-device-selector` 注册 Zod schema（title 可选 string max 200，queryParams 可选 object 含 userId/orgId/treeType/typeId）

## 4. 前端 SubDeviceSelectorBlock 组件

- [x] 4.1 创建 `frontend/src/components/genui/SubDeviceSelectorBlock.tsx`，实现组件骨架：接收 block props、useAuth、interaction 状态处理
- [x] 4.2 实现嵌入式设备选择器（左侧 OrgTreePanel + 右侧设备列表），复用 `DeviceSelectorBlock` 中 `collectDevices`、`DEVICE_TYPE_LABELS`、`getBaseUrl` 等工具函数
- [x] 4.3 实现父设备选中后调用 `GET /api/machine/component-info?machineId=<id>` 获取子设备列表
- [x] 4.4 实现子设备类型过滤逻辑（type 1→过滤80, 4→过滤50, 9→过滤100/110, 其他→全部显示）
- [x] 4.5 实现子设备列表展示和单选交互，点击子设备调用 `onInteraction(callback_id, { selected: { id, name, type, machineId } }, block_id)`
- [x] 4.6 处理所有状态：加载中、加载失败（含重试）、空列表、已提交（隐藏）、已过期（警告）、只读/禁用

## 5. 后端测试

- [x] 5.1 在 `backend/tests/test_machine_service.py` 中添加 `get_component_info_by_machine_id` 的单元测试（成功调用、携带 hiddenIfValid 参数、空响应）
