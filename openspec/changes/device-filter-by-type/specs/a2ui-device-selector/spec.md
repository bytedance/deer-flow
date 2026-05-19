## ADDED Requirements

### Requirement: filterDeviceType 参数
`device-selector` 和 `device-selector-multi` 组件 SHALL 接受可选的 `filterDeviceType` props 参数（数字类型），用于在组件内部按设备类型过滤右侧设备列表。

#### Scenario: 指定 filterDeviceType 后仅展示匹配设备
- **WHEN** Agent 渲染 `device-selector` 或 `device-selector-multi` 时 props 包含 `filterDeviceType: 4`
- **THEN** 右侧设备列表仅展示 type=4（机泵）的设备节点，其他类型的设备不显示

#### Scenario: 未指定 filterDeviceType 时展示所有设备
- **WHEN** props 中不包含 `filterDeviceType` 或其值为 `undefined`
- **THEN** 右侧设备列表展示所有 type<10 的设备节点，行为与现有逻辑一致

#### Scenario: filterDeviceType 为无效值时无匹配设备
- **WHEN** props 中 `filterDeviceType` 设置为 99（不在已定义的设备类型范围内）
- **THEN** 右侧设备列表为空，显示"该组织节点下无设备"

### Requirement: filterDeviceType Props 安全校验
`filterDeviceType` SHALL 受 sanitizer 白名单和 Zod schema 双重校验。

#### Scenario: 白名单过滤
- **WHEN** sanitizeProps 处理 `device-selector` 或 `device-selector-multi` 组件的 props
- **THEN** `filterDeviceType` 在白名单中，不被丢弃

#### Scenario: Zod 校验通过
- **WHEN** `filterDeviceType` 为合法数字
- **THEN** Zod 校验通过，组件正常渲染

#### Scenario: Zod 校验失败
- **WHEN** `filterDeviceType` 为非数字类型（如字符串）
- **THEN** Zod 校验失败，GenUIRenderer 显示校验错误信息

## MODIFIED Requirements

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
- **THEN** 右侧仅列出该组织节点及其子孙中 type<10 且（如果指定了 filterDeviceType）type 等于 filterDeviceType 的设备节点，按 displayOrder 排序
