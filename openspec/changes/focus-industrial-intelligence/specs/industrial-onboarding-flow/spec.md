## ADDED Requirements

### Requirement: 工业新用户引导触发条件
系统 SHALL 在用户首次进入工作台时检测是否已完成过工业场景操作（设备诊断、监测分析、趋势报告），如未完成则触发工业引导流程。

#### Scenario: 首次进入触发引导
- **WHEN** 用户首次进入工作台且无工业场景操作记录
- **THEN** 系统 SHALL 展示工业引导 Overlay

#### Scenario: 已完成工业操作不触发
- **WHEN** 用户进入工作台且已有工业场景操作记录
- **THEN** 系统 SHALL NOT 展示工业引导 Overlay

### Requirement: 引导流程包含 3-5 步
工业引导流程 SHALL 包含以下步骤：(1) 欢迎与产品定位介绍，(2) 选择一台设备或场景，(3) 执行一次快速诊断或分析，(4) 查看结果报告，(5) 引导至主工作台。

#### Scenario: 引导步骤完整
- **WHEN** 用户开始工业引导流程
- **THEN** 系统 SHALL 按顺序展示 5 个步骤
- **AND** 每个步骤 SHALL 有明确的"下一步"和"跳过"按钮

#### Scenario: 引导中使用示例数据
- **WHEN** 用户在引导步骤 2 中没有自己的设备数据
- **THEN** 系统 SHALL 提供示例设备和示例数据供用户体验

### Requirement: 引导可跳过
用户 SHALL 能够在引导流程的任意步骤选择跳过，跳过后引导 SHALL NOT 再次自动触发。

#### Scenario: 用户跳过引导
- **WHEN** 用户在引导任意步骤点击"跳过"
- **THEN** 引导 Overlay SHALL 立即关闭
- **AND** 用户偏好中 SHALL 标记引导已完成
- **AND** 下次进入工作台时 SHALL NOT 再次触发引导

### Requirement: 引导完成标记
系统 SHALL 在用户完成或跳过引导流程后，在用户偏好中记录引导状态，避免重复展示。

#### Scenario: 引导完成后持久化状态
- **WHEN** 用户完成引导流程最后一步或点击跳过
- **THEN** 系统 SHALL 调用 API 更新用户偏好中的 `industrial_onboarding_completed` 字段为 `true`

#### Scenario: 状态跨会话保持
- **WHEN** 用户退出后重新登录
- **THEN** 系统 SHALL 读取用户偏好，不再展示引导 Overlay

### Requirement: 引导不影响主流程入口
工业引导流程 SHALL 作为 Overlay 展示，不改变工作台的主布局和功能入口。

#### Scenario: 引导期间主工作台可见
- **WHEN** 引导 Overlay 展示时
- **THEN** 主工作台 SHALL 在 Overlay 背后可见（半透明遮罩）
- **AND** 用户 SHALL 能够通过关闭 Overlay 立即回到主工作台
