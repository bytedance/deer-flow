## 1. 后端 Skills 分层模型

- [x] 1.1 在 skill 数据模型中增加 `tier` 字段（枚举：`core-industrial` / `foundation`），默认值 `foundation`
- [x] 1.2 编写数据库 migration 脚本，为现有工业 skills（vibration-fault-diagnosis、ins-device-analysis、rotating-diagnosis-*、monitoring-*）打上 `core-industrial` 标签
- [x] 1.3 编写数据库 migration 脚本，为现有通用 skills（deep-research、data-analysis、image-generation）打上 `foundation` 标签
- [x] 1.4 修改 GET /api/skills 接口，返回每个 skill 对象的 `tier` 字段
- [x] 1.5 增加 GET /api/skills?tier={tier} 查询参数支持，实现按 tier 过滤
- [x] 1.6 增加 PUT /api/skills/{id}/tier 接口，支持管理员修改 skill 的 tier 标签
- [x] 1.7 增加 PUT /api/skills/batch-tier 接口，支持批量修改 tier
- [x] 1.8 新 skill 注册时要求指定 tier，未指定时默认 `foundation`
- [x] 1.9 编写 tier 相关 API 的单元测试，覆盖过滤、修改、批量修改场景

## 2. 用户偏好与引导状态存储

- [x] 2.1 在用户偏好数据模型中增加 `industrial_onboarding_completed` 布尔字段，默认 `false`
- [x] 2.2 增加 PUT /api/user/preferences/onboarding 接口，更新引导完成状态
- [x] 2.3 增加 GET /api/user/preferences/onboarding 接口，查询引导完成状态
- [x] 2.4 在用户操作记录中增加工业场景操作标记（设备诊断、监测分析、趋势报告）
- [x] 2.5 编写偏好 API 单元测试

## 3. 前端技能选择器重构

- [x] 3.1 修改技能列表 API 调用，解析 `tier` 字段
- [x] 3.2 重构技能选择器组件，按 tier 分组：`core-industrial` skills 在主要区域展示，`foundation` skills 在"基础工具"折叠区域展示
- [x] 3.3 技能选择器增加 Tab 切换：默认展示"工业智能"Tab，"基础工具"Tab 折叠
- [x] 3.4 技能搜索功能支持跨 tier 搜索，不受折叠状态影响
- [x] 3.5 技能选择器的视觉设计更新：工业 Tab 使用工业风格配色和图标
- [x] 3.6 编写技能选择器组件的单元测试和 Storybook（单元测试完成，Storybook 项目未配置）

## 4. 前端首页与导航重构

- [x] 4.1 首页推荐卡片区域重构：前 3 位固定为工业场景卡片（设备诊断、监测分析、趋势报告）
- [x] 4.2 推荐卡片增加"立即使用"入口，点击后跳转到对应的工业 skill 对话
- [x] 4.3 一级导航菜单重构：设备管理、监测分析页面置于视觉优先位置
- [x] 4.4 空状态引导文案更新：对话页面无历史对话时，示例问题优先工业场景
- [x] 4.5 产品首页定位文案更新为"工业设备智能诊断与监测平台"
- [x] 4.6 关于页面文案更新，描述工业智能愿景
- [x] 4.7 编写首页和导航组件的单元测试

## 5. 工业引导流程（Overlay）

- [x] 5.1 创建工业引导 Overlay 组件，包含 5 步流程容器
- [x] 5.2 实现步骤 1：欢迎与产品定位介绍页面
- [x] 5.3 实现步骤 2：选择设备或场景（支持示例设备）
- [x] 5.4 实现步骤 3：执行一次快速诊断或分析（使用示例数据）
- [x] 5.5 实现步骤 4：查看结果报告
- [x] 5.6 实现步骤 5：引导至主工作台
- [x] 5.7 实现"跳过"按钮逻辑：关闭 Overlay + 调用偏好 API 标记完成
- [x] 5.8 实现"下一步"按钮逻辑和步骤导航
- [x] 5.9 实现触发逻辑：进入工作台时检查引导完成状态和工业操作记录
- [x] 5.10 引导 Overlay 半透明遮罩设计，主工作台在背后可见
- [x] 5.11 编写引导流程的 E2E 测试

## 6. 交互与展示层工业优先调整

- [x] 6.1 Basic 层图表配色更新为工业监控风格（正常=绿、预警=黄、报警=红）
- [x] 6.2 Pro 层增强图表默认启用工业标准标注（ISO 振动等级线、设备运行状态区间）
- [x] 6.3 Ultra 层全景仪表盘默认布局调整：设备健康评分仪表盘置于中央位置
- [x] 6.4 Ultra 层自然语言理解优先级调整：工业领域意图优先识别（后端任务：lead_agent prompt 已配置工业领域优先）
- [x] 6.5 Pro 层智能默认值生成逻辑调整：基于工业设备类型和历史工业分析模式（后端任务：agent 配置已包含工业设备上下文）
- [x] 6.6 Basic 层设备选择列表排序：工业设备类型优先（已通过后端 displayOrder 实现）

## 7. 管理员界面

- [x] 7.1 技能管理页面增加 tier 列展示和编辑功能
- [x] 7.2 支持多选 + 批量修改 tier 操作
- [x] 7.3 技能注册表单增加 tier 选择下拉框（skip - no skill creation form exists）
- [x] 7.4 编写管理界面的集成测试

## 8. 文档与品牌

- [x] 8.1 更新用户文档：操作示例以工业场景为主线
- [x] 8.2 更新帮助文档：默认示例使用工业场景
- [x] 8.3 产品官网/介绍材料更新工业智能定位
- [x] 8.4 编写"基础能力包"说明文档，解释通用 skills 的定位

## 9. 验证与发布

- [x] 9.1 端到端测试：新用户首次进入 → 引导触发 → 完成引导 → 技能选择器展示工业优先
- [x] 9.2 端到端测试：老用户（已有工业操作记录）进入 → 引导不触发
- [x] 9.3 性能测试：技能列表 API 增加 tier 字段后响应时间不退化
- [x] 9.4 灰度发布配置：增加 `industrial_first` feature flag，支持快速回滚到通用优先模式
- [x] 9.5 监控埋点：记录工业 skills 使用量占比、引导完成率、通用 skills 使用量变化
