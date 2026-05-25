## Context

DeerFlow 当前已实现 18 个功能模块，覆盖 Agent Workspace、Capability Platform、Knowledge & Retrieval、Report & Output、Closed Loop、Platform Governance、Enterprise Integration 和 Industry 八大能力域。但缺少一份统一的"第一主流程"定义和"主对象模型"基线。

现有文档中：
- `docs/system-capability-map.md` 按能力域归类和审视
- `docs/system-capability-matrix.md` 按模块建立定责和投资结论
- `CLAUDE.md` 包含详细架构和对象描述，但分散在各章节

本设计文档定义输出物的格式、来源和分析方法。产出物为 3 份 Markdown 文件 + 1 个 Mermaid 流程图。

## Goals / Non-Goals

**Goals:**
- 产出一份跨产品/前端/后端均可引用的主流程图（Mermaid）
- 产出一份 8 个核心对象模型清单，明确每个对象的职责、状态和关系
- 分类工作台一级导航为主入口 vs 扩展域
- 列出未决问题清单

**Non-Goals:**
- 不修改任何代码或 API
- 不修改数据库 schema
- 不修改前端路由或导航结构
- 不涉及具体的 UI 改版或交互优化
- 不重新定义已有模块的业务逻辑

## Decisions

### D1: 主流程用 Mermaid flow 图表示

**选择**: 使用 Mermaid `flowchart LR` 从左到右展示主链，节点为对象类型，边为跳转关系。
**理由**: Markdown 原生可渲染，无需外部工具；易于版本控制和评审。
**备选方案**: Draw.io / Excalidraw → 需要额外二进制文件，不利于 diff 和版本管理。

### D2: 对象模型用表格 + 状态图表示

**选择**: 每个对象一张定义表（名称、职责、生命周期状态、关键 API、关联对象）+ 必要时用 Mermaid `state` 图表示状态机。
**理由**: 表格结构清晰，产品/前端/后端都能直接引用。状态图让生命周期边界可视化。

### D3: 导航分类基于现有路由结构

**选择**: 从 `frontend/src/app/workspace/` 目录和 `workspace-nav-chat-list.tsx` 中提取现有导航项，按"主入口 / 扩展域 / 管理后台"三类归档。
**理由**: 不凭空设计，基于已实现的路由进行分类。

### D4: 产出物放入 docs/ 而非 openspec/specs/

**选择**: 主流程图和对象模型放在 `docs/primary-flow/` 下，作为长期维护的基线文档。
**理由**: 这不是某个功能迭代的 spec，而是跨模块的系统基线。放 docs/ 更便于产品/架构长期引用。

## Risks / Trade-offs

- **[精度风险] 文档与代码不一致** → 在 ISSUE-02 实施时做一次校验对齐
- **[维护风险] 后续功能迭代可能偏离基线** → 在每个涉及主链对象的 issue 验收时对照基线检查
- **[边界风险] 对象间的职责分界可能有歧义** → 未决问题单独列出，不影响已达成共识的部分

## Open Questions

1. "任务/对话"概念是否需要拆分？当前 thread 承载了聊天会话和任务执行双重语义
2. artifact 和 report run 的产物是否有概念重叠？两者都产出文件但生命周期不同
3. closure ticket 是否应该和 report run 共享 thread 上下文，还是独立？
