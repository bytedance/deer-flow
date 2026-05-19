## Context

当前系统已有 `device-selector` 和 `device-selector-multi` A2UI 组件用于选择顶层设备（旋转机组、机泵等，type < 10）。但这些组件无法选择设备下的子设备/部件（如旋转机组下的测点 type=80，机泵下的轴承 type=50）。工业诊断 Agent 需要精确指定诊断目标到子设备级别，因此需要一个新的 A2UI 交互组件。

Java 后端已提供 `ins-bus-rpc /getComponentInfoByMachineId` 接口，可根据设备 machineId 查询该设备下的部件（ComponentInfo）列表。该接口已存在，本项目仅需在 Python 侧封装 RPC 调用并创建 Gateway 代理端点。

## Goals / Non-Goals

**Goals:**
- 新增 `sub-device-selector` A2UI 组件，包含内置单选设备选择器（复用组织树+设备列表布局）和子设备列表
- 选中父设备后自动调用后端获取子设备列表，并根据父设备类型过滤子设备类型
- 点击子设备项即回传选择结果给 Agent（与 `device-selector` 一致的单选交互）

**Non-Goals:**
- 不支持子设备多选（保持与现有 `device-selector-multi` 分离的设计模式）
- 不提供独立的组织树 API（复用现有 `/api/organize/tree`）
- 不修改现有 `DeviceSelectorBlock` 或 `DeviceSelectorMultiBlock` 组件
- 不支持嵌套子设备（仅一层：设备 → 子设备）

## Decisions

### 1. 组件架构：全新独立组件 `SubDeviceSelectorBlock`

选择创建全新组件而非扩展现有 `DeviceSelectorBlock`。

**理由：**
- `DeviceSelectorBlock` 的职责是单选顶层设备并立即回传，`SubDeviceSelectorBlock` 的交互是"先选设备 → 加载子设备 → 选子设备回传"，两步交互流程完全不同
- 保持现有组件不变，避免引入回归风险
- 符合 registry 中 `device-selector` / `device-selector-multi` 独立注册的模式

**备选方案（已排除）：** 通过 props 配置 `DeviceSelectorBlock` 进入"子设备模式"。排除原因：会增加组件内部分支复杂度，props 语义混乱，且两步交互的状态管理会污染现有单向数据流。

### 2. 子设备类型过滤：前端硬编码映射表

根据父设备 `type` 过滤子设备 `type`：

| 父设备类型 | 父设备名称 | 子设备过滤 type |
|-----------|-----------|----------------|
| 1 | 旋转机组 | 80 |
| 4 | 机泵 | 50 |
| 9 | 往复机 | 100, 110 |

**理由：**
- 业务规则固定且明确，无需后端动态配置
- 避免增加额外的配置查询 API
- 与现有 `DEVICE_TYPE_LABELS` 常量模式一致

### 3. RPC 客户端：扩展现有 `MachineServiceClient`

在 `MachineServiceClient` 中新增 `get_component_info_by_machine_id()` 方法。

**理由：**
- `getComponentInfoByMachineId` 端点挂载在 `ins-bus-rpc` 服务下，与现有 `MachineServiceClient` 的服务和路径前缀一致
- 避免为单一方法创建新 service 文件
- `MachineServiceClient` 已有 `_unwrap_ajax_result` 用于解包 AjaxResult

### 4. Gateway 代理端点：独立路由文件 `routers/machine.py`

创建新文件 `backend/app/gateway/routers/machine.py`，注册为 `/api/machine` 前缀。

**理由：**
- 目前 `routers/` 下尚无 machine 路由，新增不存在冲突
- 遵循 `organize.py` 的路由模式：懒初始化客户端、异常统一处理为 502
- 后续 machine 相关端点（如 `getMachineInfoByIds` 已有 RPC 封装）可同文件扩展

## Risks / Trade-offs

- **RPC 超时风险**：`getComponentInfoByMachineId` 对于大型设备可能返回较多子设备（ComponentInfo 含递归 childs 字段）。→ 设置合理的前端加载状态，RPC 客户端沿用默认 30s 超时。
- **设备类型映射不完整**：当前仅处理 type 1/4/9 三种父设备类型的子设备过滤。→ 若选中其他类型设备（如静设备 type=6），RPC 返回全量子设备列表但不做 type 过滤，由用户自行选择。
- **子设备列表可能为空**：部分设备可能无子设备。→ 组件展示"该设备下无子设备"占位提示。
