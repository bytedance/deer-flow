# a2ui-sub-device-selector

## Purpose

Provides the `sub-device-selector` A2UI interactive component. Users first select a parent device via an embedded organization tree + device list, then the component fetches the device's sub-devices (components) from the backend and displays them for single selection. The selection is communicated back to the agent via `onInteraction` callbacks.

## ADDED Requirements

### Requirement: 子设备选择器组件注册
系统 SHALL 在 A2UI 组件注册表中注册 `sub-device-selector` 组件，类型为交互式组件。

#### Scenario: 组件正常加载
- **WHEN** GenUIRenderer 收到 component 为 `sub-device-selector` 的 UIBlock
- **THEN** 系统从 registry 中懒加载 SubDeviceSelectorBlock 组件并渲染

#### Scenario: 未知组件回退
- **WHEN** schema_version 主版本号大于当前支持版本
- **THEN** 系统回退到 markdown 组件渲染

### Requirement: 组件属性定义
`sub-device-selector` 组件 SHALL 接受以下属性：
- `title`（可选 string）：组件标题
- `queryParams`（可选 object）：组织树查询参数，包含 `userId`、`orgId`、`treeType`、`typeId`

#### Scenario: 传递 queryParams
- **WHEN** UIBlock 的 props 包含 `queryParams: { userId: "1", orgId: 0, treeType: 1 }`
- **THEN** 组件使用指定的参数请求组织树 API

#### Scenario: 未传递 queryParams
- **WHEN** UIBlock 的 props 未包含 queryParams
- **THEN** 组件使用默认参数（userId 从认证上下文获取，orgId=0，treeType=1）请求组织树

### Requirement: 属性白名单注册
系统 SHALL 在属性清理器（sanitizer）中为 `sub-device-selector` 注册白名单，仅允许 `title` 和 `queryParams` 属性通过。

#### Scenario: 白名单过滤
- **WHEN** UIBlock 包含非白名单属性
- **THEN** 清理器仅保留 `title` 和 `queryParams`，其余属性被丢弃

### Requirement: 属性 Zod 校验
系统 SHALL 在验证器（validator）中为 `sub-device-selector` 注册 Zod schema，校验 `title` 为可选字符串（最大 200 字符），`queryParams` 为可选对象（包含可选 `userId` string、`orgId` number、`treeType` number、`typeId` number）。

#### Scenario: 有效属性校验通过
- **WHEN** 传入 `{ title: "选择子设备", queryParams: { treeType: 1 } }`
- **THEN** 校验通过，返回清洗后的属性

#### Scenario: title 超长校验失败
- **WHEN** 传入 `{ title: "a".repeat(201) }`
- **THEN** 校验失败，记录错误

### Requirement: 嵌入式设备选择器
组件 SHALL 包含嵌入式单选设备选择器，用于选择父设备。交互模式与 `device-selector` 一致：左侧组织树、右侧设备列表、单选点击。

#### Scenario: 渲染设备选择器
- **WHEN** 组件挂载并完成组织树 API 调用
- **THEN** 左侧显示组织树（type>=10 的组织节点），右侧显示设备列表（type<10 的设备节点）

#### Scenario: 选中父设备
- **WHEN** 用户点击右侧设备列表中的一个设备项
- **THEN** 该设备被选中高亮，组件自动发起子设备查询

### Requirement: 父设备类型显示
系统 SHALL 在设备列表中将 type 转换为中文标签显示。支持的类型标签：1=旋转机组、4=机泵、6=静设备、9=往复机组。

#### Scenario: 显示设备类型标签
- **WHEN** 设备列表中包含 type=1 的设备
- **THEN** 该设备名称旁显示"(旋转机组)"标签

### Requirement: 子设备列表查询
选中父设备后，系统 SHALL 调用 `GET /api/machine/component-info?machineId=<id>` 获取该设备下的子设备列表。

#### Scenario: 查询成功
- **WHEN** 用户选中一个设备且 API 返回子设备列表
- **THEN** 组件展示子设备列表供用户选择

#### Scenario: 查询失败
- **WHEN** API 请求失败（网络错误或服务不可用）
- **THEN** 组件显示错误信息并提供重试按钮

#### Scenario: 查询进行中
- **WHEN** API 请求进行中
- **THEN** 子设备列表区域显示加载状态

#### Scenario: 子设备列表为空
- **WHEN** API 返回空列表
- **THEN** 子设备列表区域显示"该设备下无子设备"提示

### Requirement: 子设备类型过滤
系统 SHALL 根据父设备的 type 过滤子设备列表中的子设备 type：

| 父设备 type | 父设备名称 | 子设备显示 type |
|------------|-----------|----------------|
| 1 | 旋转机组 | 80 |
| 4 | 机泵 | 50 |
| 9 | 往复机 | 100, 110 |
| 其他 | — | 不过滤（显示全部） |

#### Scenario: 旋转机组过滤子设备
- **WHEN** 用户选中 type=1 的旋转机组
- **THEN** 子设备列表仅显示 type=80 的子设备

#### Scenario: 机泵过滤子设备
- **WHEN** 用户选中 type=4 的机泵
- **THEN** 子设备列表仅显示 type=50 的子设备

#### Scenario: 往复机过滤子设备
- **WHEN** 用户选中 type=9 的往复机
- **THEN** 子设备列表仅显示 type 为 100 或 110 的子设备

#### Scenario: 其他类型不过滤
- **WHEN** 用户选中 type=6 的静设备或其他未定义类型的设备
- **THEN** 子设备列表显示 API 返回的全部子设备

### Requirement: 子设备单选交互
系统 SHALL 在子设备列表中仅允许选择一个子设备，点击即选中并立即通过 `onInteraction` 回传。

#### Scenario: 选中子设备
- **WHEN** 用户点击子设备列表中的一个子设备项
- **THEN** 该子设备高亮，系统调用 `onInteraction(callback_id, { selected: { id, name, type, machineId } }, block_id)`

#### Scenario: 切换子设备选择
- **WHEN** 用户点击另一个子设备项
- **THEN** 之前选中的子设备取消高亮，新子设备高亮，回传新的选择结果

### Requirement: 已提交状态
系统 SHALL 在 interaction 状态为 `submitted` 时隐藏组件。

#### Scenario: 提交后隐藏
- **WHEN** interactionState.status 为 "submitted"
- **THEN** 组件返回 null，不渲染任何内容

### Requirement: 已过期状态
系统 SHALL 在 interaction 状态为 `expired` 时显示过期提示。

#### Scenario: 显示过期提示
- **WHEN** interactionState.status 为 "expired"
- **THEN** 组件显示黄色警告提示"This selector has expired."

### Requirement: 禁用状态
系统 SHALL 在 interaction 状态为 `loading`、`submitted`、`expired` 或 `readonly` 时禁用所有交互操作。

#### Scenario: 交互禁用
- **WHEN** interactionState.status 为 "loading"
- **THEN** 设备列表项和子设备列表项均不可点击（disabled 状态）

### Requirement: 错误状态显示
系统 SHALL 在 interaction 状态为 `error` 时显示错误信息。

#### Scenario: 显示交互错误
- **WHEN** interactionState.status 为 "error" 且 interactionState.error 有值
- **THEN** 组件底部显示红色错误提示文字

### Requirement: 后端 RPC 封装
系统 SHALL 在 `MachineServiceClient` 中新增 `get_component_info_by_machine_id(machine_id, hidden_if_valid)` 方法，调用 `ins-bus-rpc /getComponentInfoByMachineId` GET 端点并解包 AjaxResult 返回子设备列表。

#### Scenario: RPC 调用成功
- **WHEN** 调用 `get_component_info_by_machine_id(12345, False)`
- **THEN** 返回 ComponentInfo 列表（dict 格式）

#### Scenario: 可选参数 hiddenIfValid
- **WHEN** 调用 `get_component_info_by_machine_id(12345, True)`
- **THEN** RPC 请求携带 `hiddenIfValid=true` 参数

### Requirement: Gateway 代理端点
系统 SHALL 创建 `GET /api/machine/component-info` 端点，接受 `machineId`（必填 int）和 `hiddenIfValid`（可选 bool）查询参数，代理到 `MachineServiceClient.get_component_info_by_machine_id()`。

#### Scenario: 代理成功
- **WHEN** 前端请求 `GET /api/machine/component-info?machineId=12345`
- **THEN** 返回子设备列表 JSON

#### Scenario: 服务不可用
- **WHEN** RPC 调用抛出异常
- **THEN** 返回 HTTP 502 及错误详情

### Requirement: Gateway 路由注册
系统 SHALL 在 `app.py` 中注册 machine 路由模块。

#### Scenario: 路由可用
- **WHEN** Gateway 启动
- **THEN** `/api/machine/component-info` 端点可访问
