## Why

产品当前同时服务两类用户：通用知识工作者和工业设备工程师。通用 skills（deep-research、data-analysis、image-generation）与工业 skills（vibration-fault-diagnosis、ins-device-analysis）共存，导致产品定位模糊、资源分散、用户体验割裂。需要明确工业智能为主赛道，将通用能力降级为基础能力包，集中资源打造工业智能核心竞争力。

## What Changes

- **产品定位重构**：将产品定位从"通用 AI 助手"调整为"工业智能平台"，所有新功能开发优先服务工业场景
- **Skills 分层管理**：将现有 skills 分为两层：
  - **核心工业层**：vibration-fault-diagnosis、ins-device-analysis、rotating-diagnosis-*、monitoring-* 等工业专用 skills，作为产品差异化核心
  - **基础能力包**：deep-research、data-analysis、image-generation 等通用 skills，降级为可选的基础工具，默认不展示
- **UI/UX 重设计**：首页、导航、推荐流程优先展示工业场景，通用能力退居二级入口
- **资源分配调整**：新功能开发、性能优化、文档建设优先服务工业智能主线
- **技能市场定位**：如果未来开放技能市场，工业 skills 作为付费核心，通用 skills 作为免费基础包

## Capabilities

### New Capabilities

- `industrial-first-positioning`: 产品定位从通用转向工业优先的整体策略，包括品牌、入口、推荐逻辑的重构
- `skill-tier-management`: Skills 分层管理体系，定义核心工业层与基础能力包的分类标准、展示策略、启用规则
- `industrial-onboarding-flow`: 面向工业用户的首次使用引导流程，快速展示工业智能核心价值

### Modified Capabilities

- `primary-flow-definition`: 主流程定义需要从通用场景调整为工业场景优先，默认推荐工业诊断/监测流程
- `interaction-mode-tiers`: 交互模式分层需要增加"工业专家模式"作为默认推荐模式
- `result-presentation-tiers`: 结果展示需要优先支持工业报告格式（振动分析、监测报告等）

## Impact

- **前端代码**：首页组件、导航菜单、技能选择器需要重构，工业 skills 前置展示
- **后端配置**：Skills 注册表需要增加分层标签（tier: core-industrial / foundation），支持按层过滤
- **API 接口**：技能列表接口需要返回 tier 信息，支持客户端按层展示
- **文档体系**：用户文档需要重新组织，工业智能文档作为主线，通用能力文档作为附录
- **营销与品牌**：产品官网、介绍材料需要突出工业智能定位
- **团队认知**：需要在团队内部明确"工业优先"的产品原则，影响后续需求评审标准
