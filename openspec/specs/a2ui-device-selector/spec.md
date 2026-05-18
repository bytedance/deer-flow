# a2ui-device-selector

## Purpose

Provides A2UI interactive components for device selection within the industrial monitoring platform. Users browse an organization tree and select one or multiple devices, with the selection communicated back to the agent via `onInteraction` callbacks. Tree data is fetched at runtime from the Gateway proxy endpoint.

## Requirements

### Requirement: 设备单选选择器组件注册
系统 SHALL 在 A2UI 组件注册表中注册 `device-selector` 组件，类型为交互式组件。

#### Scenario: 组件正常加载
- **WHEN** GenUIRenderer 收到 component 为 `device-selector` 的 UIBlock
- **THEN** 系统从 registry 中懒加载 DeviceSelectorBlock 组件并渲染

#### Scenario: 未知组件回退
- **WHEN** schema_version 主版本号大于当前支持版本
- **THEN** 系统回退到 markdown 组件渲染

### Requirement: 设备多选选择器组件注册
系统 SHALL 在 A2UI 组件注册表中注册 `device-selector-multi` 组件，类型为交互式组件。

#### Scenario: 组件正常加载
- **WHEN** GenUIRenderer 收到 component 为 `device-selector-multi` 的 UIBlock
- **THEN** 系统从 registry 中懒加载 DeviceSelectorMultiBlock 组件并渲染

### Requirement: 左右分栏布局
系统 SHALL 以左右分栏布局展示设备选择器：左侧为可折叠的组织树，右侧为选中组织节点下的设备列表。

#### Scenario: 渲染完整布局
- **WHEN** 设备选择器挂载并完成组织树 API 调用
- **THEN** 左侧显示可折叠的组织树（仅展示 type>=10 的组织节点），右侧显示"请选择组织节点"占位提示

#### Scenario: 左侧组织树展开折叠
- **WHEN** 用户点击左侧组织树中一个折叠的组织节点
- **THEN** 该节点展开显示子组织节点，右侧设备列表切换为该组织节点下的设备

#### Scenario: API 加载失败
- **WHEN** 组织树 API 请求失败
- **THEN** 系统显示错误信息并提供重试按钮

#### Scenario: 组织节点右侧设备类型过滤
- **WHEN** 左侧选中某组织节点
- **THEN** 右侧仅列出该组织节点及其子孙中 type<10 的设备节点（type=1 旋转机组、type=4 机泵、type=6 静设备、type=9 往复机组），按 displayOrder 排序

### Requirement: 单选模式交互
`device-selector` 组件 SHALL 在右侧设备列表中仅允许选择一个设备，点击即选中并立即通过 onInteraction 回传。

#### Scenario: 选中设备
- **WHEN** 用户点击右侧设备列表中的一个设备项
- **THEN** 该设备项高亮为选中状态，系统调用 onInteraction 回传 `{ selected: { id, label, type, path } }`

#### Scenario: 切换选中
- **WHEN** 已有一个选中设备，用户点击右侧另一个设备项
- **THEN** 前一个设备取消选中，新设备高亮选中，系统再次调用 onInteraction 回传新设备信息

#### Scenario: 切换组织节点后选中
- **WHEN** 用户在左侧切换到另一个组织节点，然后点击右侧某设备
- **THEN** 右侧刷新为该组织节点下的设备列表，选中的设备正常回传

### Requirement: 多选模式交互
`device-selector-multi` 组件 SHALL 在右侧设备列表中允许用户通过复选框选择多个设备，提交后通过 onInteraction 回传。

#### Scenario: 勾选多个设备
- **WHEN** 用户依次勾选右侧三个设备的复选框
- **THEN** 三个设备均显示为选中状态，底部计数显示"已选: 3"

#### Scenario: 取消勾选
- **WHEN** 用户点击已选中设备的复选框
- **THEN** 该设备取消选中，底部计数相应减少

#### Scenario: 跨组织节点多选
- **WHEN** 用户在组织节点A下勾选了2个设备，切换到组织节点B又勾选了3个设备
- **THEN** 系统应保留跨节点的全部5个选中设备，通过提交按钮统一回传

#### Scenario: 提交选中
- **WHEN** 用户至少选中一个设备并点击提交按钮
- **THEN** 系统调用 onInteraction 回传 `{ selected: [{ id, label, type, path }] }`

#### Scenario: 未选中提交
- **WHEN** 用户未选中任何设备即点击提交按钮
- **THEN** 提交按钮处于禁用状态，无法提交

### Requirement: maxSelect 限制
`device-selector-multi` 组件 SHALL 在配置了 maxSelect 参数时限制最大可选设备数量。

#### Scenario: 超出最大可选数
- **WHEN** maxSelect=5 且已选中5个设备，用户尝试勾选第6个设备
- **THEN** 第6个设备的复选框处于禁用状态或显示提示

### Requirement: Props 安全校验
`device-selector` 和 `device-selector-multi` 的 props SHALL 受 sanitizer 白名单和 Zod schema 双重校验。

#### Scenario: 白名单外的 props 被丢弃
- **WHEN** UIBlock 的 props 中包含组件白名单之外的键
- **THEN** sanitizeProps 静默丢弃这些键，组件仅使用白名单内的 props

#### Scenario: 无效 props 类型
- **WHEN** queryParams 不是合法的对象格式
- **THEN** Zod 校验失败，GenUIRenderer 显示校验错误信息

#### Scenario: 校验通过
- **WHEN** props 包含合法的 queryParams、title 等字段
- **THEN** Zod 校验通过，组件正常渲染

### Requirement: 前端调用组织树 API
设备选择器组件 SHALL 在挂载时通过 Gateway 代理端点自行获取组织树数据，而非接收后端注入的 treeData。

#### Scenario: 组件挂载时获取数据
- **WHEN** DeviceSelectorBlock 或 DeviceSelectorMultiBlock 组件挂载
- **THEN** 组件从 `/api/organize/tree` 发起 GET 请求，携带 queryParams 中的参数，在加载完成后渲染组织树

#### Scenario: 使用默认查询参数
- **WHEN** props 中未提供 queryParams 或其字段缺失
- **THEN** 使用默认值 userId=1、orgId=0、treeType=1

### Requirement: 后端组织树 Gateway 代理端点
系统 SHALL 提供 `GET /api/organize/tree` 端点代理 ins-bus-rpc 服务的组织树查询。

#### Scenario: 代理设备树查询
- **WHEN** 前端请求 `GET /api/organize/tree?userId=1&orgId=0&treeType=1`
- **THEN** Gateway 通过 OrganizeServiceClient 向 ins-bus-rpc 发起请求，返回组织树数据

#### Scenario: 携带搜索条件
- **WHEN** 请求携带 content="常减压"
- **THEN** 返回过滤后的树节点

#### Scenario: 后端服务不可用
- **WHEN** ins-bus-rpc 服务返回错误
- **THEN** Gateway 返回 502 状态码及错误详情

### Requirement: 后端组织树 RPC 客户端
系统 SHALL 提供 OrganizeServiceClient 封装 ins-bus-rpc 服务的 `/organize/getOrgTreeByUserIdAndOrgId` 接口调用。

#### Scenario: 获取设备树
- **WHEN** 调用 `get_org_tree_by_user_id_and_org_id(user_id=1, org_id=0, tree_type=1)`
- **THEN** 系统通过 RpcClient 向 ins-bus-rpc 发起 GET 请求，携带 userId=1、orgId=0、treeType=1 参数，返回组织树数据列表

#### Scenario: 携带搜索条件
- **WHEN** 调用时传入 content="常减压"
- **THEN** 请求参数包含 content 过滤条件，返回过滤后的树节点
