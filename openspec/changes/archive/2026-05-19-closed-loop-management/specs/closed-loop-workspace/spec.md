## ADDED Requirements

### Requirement: 工作台导航入口
前端工作台 SHALL 在主导航中暴露「闭环管理」入口，受 feature flag `NEXT_PUBLIC_CLOSED_LOOP_ENABLED` 与权限点 `closure:read` 双重控制。

#### Scenario: 入口可见
- **WHEN** feature flag 开启且当前用户具备 `closure:read` 权限
- **THEN** 工作台侧边栏展示「闭环管理」入口，点击后进入闭环单列表页

#### Scenario: 入口隐藏
- **WHEN** feature flag 关闭，或当前用户不具备 `closure:read` 权限
- **THEN** 工作台不渲染「闭环管理」入口，直接访问 URL 也跳转到无权限提示页

### Requirement: 闭环单列表视图
闭环单列表 SHALL 展示分页表格，列至少包含：标题、设备、来源、严重等级、状态、责任人、剩余时间/超期标记、创建时间。提供按状态、设备、责任人、来源、超期标记的筛选条件，以及全文搜索。

#### Scenario: 默认排序
- **WHEN** 用户首次进入列表页
- **THEN** 列表按"未关闭优先 + due_at 升序"排序，超期单据顶置且行体高亮红色

#### Scenario: 筛选生效
- **WHEN** 用户勾选 `status=in_progress` 与 `is_overdue=true`
- **THEN** 列表只展示符合条件的单据，URL query 同步更新便于分享链接

#### Scenario: 切换页码
- **WHEN** 用户切换分页
- **THEN** 当前筛选条件保持，仅请求对应页数据

### Requirement: 闭环单看板视图
列表页 SHALL 提供"列表 / 看板"双视图切换；看板按状态分列展示卡片，本期看板为只读视图，不支持拖拽变更状态。

#### Scenario: 切换为看板
- **WHEN** 用户在列表页点击"看板"切换按钮
- **THEN** 视图按 `pending | assigned | in_progress | pending_verification | closed` 分列展示卡片，每列展示数量徽标

#### Scenario: 看板卡片点击
- **WHEN** 用户点击看板某卡片
- **THEN** 打开右侧详情抽屉，与列表点击行为一致

### Requirement: 闭环单详情抽屉
点击列表行或看板卡片 SHALL 打开右侧详情抽屉，展示完整字段、来源关联（诊断 run / 报告 run / 设备链接）、处置方案、附件、状态变更时间线。

#### Scenario: 来源链接跳转
- **WHEN** 用户在抽屉中点击"来源诊断 run"链接
- **THEN** 新标签页打开对应 run 的详情页

#### Scenario: 时间线倒序
- **WHEN** 抽屉渲染时间线
- **THEN** 时间线按发生时间倒序展示，最新事件在顶部

### Requirement: 处置与验证表单
具备 `closure:write` 权限的用户 SHALL 在抽屉中通过表单触发"派单 / 开始处置 / 提交验证 / 关闭 / 退回"等动作；表单字段按状态机当前可执行动作动态展示。

#### Scenario: 派单表单
- **WHEN** 单据处于 `pending` 且当前用户具备 `closure:write` 权限
- **THEN** 抽屉展示"派单"按钮，点击后弹出表单要求选择 `assignee` 与 `priority`，提交后调用迁移接口

#### Scenario: 验证关闭表单
- **WHEN** 单据处于 `pending_verification` 且当前用户具备 `closure:verify` 权限
- **THEN** 抽屉展示"验证关闭 / 退回"两个按钮；选择"验证关闭"需填写验证结论与对比数据后再提交

#### Scenario: 权限不足
- **WHEN** 当前用户缺少所需权限
- **THEN** 对应按钮禁用并显示 tooltip 解释所需权限

### Requirement: 待办与超期徽标
工作台 SHALL 在「闭环管理」导航项右侧展示当前用户负责的"未关闭 / 超期"数量徽标，超期数量大于 0 时徽标变红。

#### Scenario: 徽标实时刷新
- **WHEN** 后端发布 `closure.overdue` 事件且涉及当前用户负责的单据
- **THEN** 前端在 30 秒内更新徽标数字

#### Scenario: 徽标点击跳转
- **WHEN** 用户点击徽标
- **THEN** 跳转到列表页且自动应用 "我负责的 + 超期" 筛选

### Requirement: 列表与详情的乐观更新
状态迁移成功 SHALL 触发当前列表/抽屉的乐观更新，不强制全表重载。

#### Scenario: 派单成功
- **WHEN** 用户在抽屉提交派单成功
- **THEN** 抽屉立即显示新状态与责任人，列表对应行同步更新而不刷新整页

#### Scenario: 提交失败回滚
- **WHEN** 状态迁移请求返回 409 冲突
- **THEN** 抽屉回滚为请求前状态并显示错误提示
