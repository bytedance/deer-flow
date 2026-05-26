## Context

当前报告模板平台已具备完整的 DSL v1 schema、验证器、运行时工具链和 8 个 builtin 模板。模板创建流程为：开发者手写 YAML → validator 校验 → 发布到 builtin 目录。

**现状问题**:
- DSL 包含 form_steps、data_steps、transforms、sections、export 五层结构，涉及 JSONPath 引用、script registry 命名空间、step ID 唯一性约束等隐性规则
- 设备工程师了解业务需求但无法编写 YAML，导致模板创建瓶颈在开发团队
- 模板分发依赖代码提交，无租户级自服务能力
- 现有 `POST /{id}/fork` 仅支持单模板复制，无市场发现和批量分发机制

**约束**:
- 可视化编辑器输出必须 100% 兼容现有 DSL v1 schema，不需要修改 validator 或 runtime
- 市场安装的模板必须复用现有的 repository / permissions / version-traceability 基础设施
- 前端技术栈：Next.js + shadcn/ui，拖拽库选型 @dnd-kit（轻量、无障碍、无外部依赖）

## Goals / Non-Goals

**Goals:**
- 设备工程师无需编写 YAML 即可创建完整报告模板
- 模板创建时间从"天级（开发者排期）"降至"小时级（业务自助）"
- 租户管理员可在租户内发布和分享模板
- 市场提供模板发现、评分、一键安装能力
- 蓝图系统将常见模式抽象为可复用起点

**Non-Goals:**
- 不修改 DSL v1 schema 或 validator（编辑器适配 schema，而非反向）
- 不引入外部模板注册中心（如 npm registry）；市场是平台内置功能
- 不支持跨平台模板分发（本期仅单实例）
- 不实现模板的自动测试/质量评分
- 不实现可视化数据步骤编排（data_steps 配置仍为高级功能，编辑器提供表单但不做拖拽）

## Decisions

### D7: 权限模型 — 扩展 authz.py

**Decision**: 在 `app/gateway/authz.py` 的 `Permissions` 类中新增 marketplace 权限常量：

```python
MARKETPLACE_READ = "marketplace:read"      # 浏览市场
MARKETPLACE_WRITE = "marketplace:write"    # 安装、评分
MARKETPLACE_PUBLISH = "marketplace:publish" # 发布模板到市场
```

**Rationale**:

- 复用现有 `require_permission` 装饰器和 `AuthContext` 机制
- `marketplace:publish` 单独拆分，便于控制"谁能发布"与"谁能安装"
- 默认授权：superadmin + tenant_admin 获得全部三个权限；普通用户获得 read + write

### D8: 与 Insights System 的关系 — 独立系统，可选联动

**Decision**: Marketplace reviews 与 Insights System 的 feedback 是**两个独立系统**，数据不共享。但预留可选联动接口。

**Rationale**:

- Insights System 的 `FeedbackAggregator` 聚合的是**运行时反馈**（per-run，thumbs up/down），用于改进 agent 行为
- Marketplace reviews 是**模板质量信号**（per-template，1-5 星），用于模板发现
- 两者粒度和目的不同，强行合并会增加复杂度

**可选联动**（后续迭代）:

- 市场低分模板 → Insights `ImprovementEngine` 生成"模板改进建议"
- Insights 检测到某 template 的 run 频繁失败 → 市场显示"稳定性警告"徽章

### D9: 前端组件复用 — 基于现有 hooks 和 i18n

**Decision**: 编辑器/市场页面复用现有基础设施：

- TanStack Query hooks（`core/report-templates/api.ts`）用于模板 CRUD
- i18n 系统（`core/i18n/`，en-US + zh-CN）用于多语言
- shadcn/ui 组件库用于 UI 原语

**Rationale**:

- 避免重复实现已有的 API 调用、缓存、状态管理逻辑
- i18n 已有完整基础设施，新页面直接添加翻译 key 即可
- 保持代码风格一致性

### D1: 编辑器架构 — Schema-first with visual overlay

**Decision**: 编辑器以 DSL schema 为单一数据源，UI 是 schema 的可视化投影。所有编辑操作先修改内存中的 DSL 对象，UI 实时渲染。

**Rationale**: 
- 保证编辑器输出与手写 YAML 100% 兼容
- Schema 变更自动反映到 UI，无需维护两套逻辑
- 用户可随时切换到 YAML 视图进行高级编辑

**Alternatives considered**:
- *Visual-first with codegen*: UI 状态独立，导出时生成 YAML。风险：UI 状态与 schema 漂移，codegen 复杂度高
- *Hybrid with bidirectional sync*: 双向同步。风险：冲突解决复杂，edge case 多

### D2: 拖拽库选型 — @dnd-kit

**Decision**: 使用 `@dnd-kit/core` + `@dnd-kit/sortable`

**Rationale**:
- 轻量（~30KB gzipped），无外部依赖
- 原生支持键盘导航和无障碍
- 与 React 18 + Next.js 兼容性好
- shadcn/ui 生态中广泛使用

**Alternatives considered**:
- *react-beautiful-dnd*: 已停止维护
- *react-dnd*: API 复杂，bundle 较大

### D3: 市场存储 — PostgreSQL 元数据 + 文件系统 DSL

**Decision**: 市场元数据（listing、评分、安装记录）存 PostgreSQL；模板 DSL 复用现有 filesystem repository。

**Rationale**:
- 元数据需要全文搜索、聚合统计、事务一致性，PostgreSQL 更合适
- DSL 内容已是 JSON，复用 filesystem 避免重复存储
- 安装操作 = 市场元数据更新 + fork 到目标空间，复用现有 fork 机制

### D4: 蓝图系统 — 参数化模板模板

**Decision**: 蓝图是带有占位符和可选模块的"模板的模板"。用户选择蓝图后，编辑器预填 DSL 骨架，用户只需配置业务特定部分。

**Rationale**:
- 降低冷启动成本：80% 的模板结构由蓝图提供
- 蓝图可包含最佳实践（如标准 KPI 集合、推荐的 section 布局）
- 实现简单：蓝图 = 预填的 DSL + 标注哪些部分需要用户配置

**Alternatives considered**:
- *可视化模板库*: 纯 UI 组件复用。不足：无法覆盖 data_steps/transforms 层
- *AI 生成*: LLM 生成 DSL。风险：质量不可控，DSL 验证失败率高

### D5: 模板包格式 — `.template` ZIP 归档

**Decision**: `.template` 文件 = ZIP 归档，包含 `template.yaml`（DSL）、`metadata.json`、`blueprint.json`（可选）、`README.md`。

**Rationale**:
- 与现有 `.skill` 归档格式一致（复用安装基础设施）
- ZIP 格式通用，便于跨环境迁移
- 支持未来扩展（截图、示例数据）

### D6: 编辑器分步实现 — MVP 覆盖 form_steps + sections

**Decision**: MVP 阶段编辑器仅支持 form_steps 和 sections 的可视化编辑。data_steps 和 transforms 通过 YAML 编辑或表单填写（非拖拽）。

**Rationale**:
- form_steps 和 sections 占用户 80% 的编辑需求
- data_steps/transforms 涉及 script registry 知识，适合高级用户
- 降低 MVP 范围，快速验证用户价值

## Risks / Trade-offs

- **[Risk] 编辑器生成的 DSL 可能触发 validator 错误** → Mitigation: 编辑器内置实时验证，每次修改后调用 validator API 并显示错误提示；提供"修复建议"按钮
- **[Risk] 市场模板质量参差不齐** → Mitigation: 租户管理员审核机制；builtin 模板作为质量标杆；评分系统帮助发现优质模板
- **[Risk] 蓝图维护成本** → Mitigation: 蓝图从现有 builtin 模板自动生成（逆向工程），减少手工维护
- **[Trade-off] Schema-first 限制 UI 创新** → 接受：保证兼容性优先于 UI 花哨功能
- **[Trade-off] 市场不跨平台** → 接受：本期聚焦单实例，跨平台分发作为后续迭代

## Open Questions

- Q1: 市场是否需要"付费模板"机制？（本期假设：否，所有模板免费）
- Q2: 蓝图是否需要版本管理？（本期假设：蓝图跟随平台版本，不独立版本化）
- Q3: 编辑器是否需要多人协作？（本期假设：否，单人编辑 + 保存锁）
