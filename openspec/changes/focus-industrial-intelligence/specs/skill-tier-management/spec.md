## ADDED Requirements

### Requirement: Skill tier 标签模型
系统 SHALL 为每个注册的 skill 分配一个 tier 标签，取值为 `core-industrial`（核心工业层）或 `foundation`（基础能力包）。

#### Scenario: 现有 skills 标签分配
- **WHEN** 系统初始化或管理员执行标签迁移
- **THEN** vibration-fault-diagnosis、ins-device-analysis、rotating-diagnosis-*、monitoring-* 等工业专用 skills SHALL 标记为 `core-industrial`
- **AND** deep-research、data-analysis、image-generation 等通用 skills SHALL 标记为 `foundation`

#### Scenario: 新 skill 注册时指定 tier
- **WHEN** 管理员注册一个新的 skill
- **THEN** 系统 SHALL 要求管理员指定该 skill 的 tier 标签
- **AND** 未指定时默认值为 `foundation`

### Requirement: 技能列表 API 返回 tier 信息
技能列表 API（GET /api/skills）SHALL 在返回的每个 skill 对象中包含 `tier` 字段。

#### Scenario: API 响应包含 tier
- **WHEN** 客户端调用 GET /api/skills
- **THEN** 响应中每个 skill 对象 SHALL 包含 `tier` 字段，值为 `core-industrial` 或 `foundation`

#### Scenario: 按 tier 过滤
- **WHEN** 客户端调用 GET /api/skills?tier=core-industrial
- **THEN** 响应 SHALL 仅返回 tier 为 `core-industrial` 的 skills

### Requirement: 技能选择器分层展示
前端技能选择器 SHALL 按 tier 分组展示 skills：核心工业层 skills 在主要区域展示，基础能力包 skills 在折叠区域展示。

#### Scenario: 分层展示
- **WHEN** 用户打开技能选择器
- **THEN** 核心工业层 skills SHALL 在主要区域（Tab 或卡片网格）直接可见
- **AND** 基础能力包 skills SHALL 在"基础工具"折叠区域内，需要用户主动展开才可见

#### Scenario: 搜索可达
- **WHEN** 用户在技能选择器中搜索 skill 名称
- **THEN** 搜索结果 SHALL 包含所有 tier 的 skills，不受折叠状态影响

### Requirement: Tier 标签可配置
系统 SHALL 提供管理员界面，允许管理员修改 skill 的 tier 标签。

#### Scenario: 管理员修改 tier
- **WHEN** 管理员在技能管理页面修改某个 skill 的 tier 标签
- **THEN** 修改 SHALL 立即生效，前端技能选择器在下一次刷新时反映变更

#### Scenario: 批量修改 tier
- **WHEN** 管理员选中多个 skills 并批量修改 tier
- **THEN** 所有选中的 skills 的 tier SHALL 被更新
