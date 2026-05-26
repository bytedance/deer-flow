## Why

DSL 驱动的报告模板是当前系统的核心差异化能力，但 DSL 编写门槛过高——设备工程师（最终用户）无法直接编写 YAML 模板。当前 8 个内置模板由开发者手工编写，模板创建依赖开发团队，严重制约了模板的多样性和业务覆盖速度。需要构建可视化模板编辑器和模板市场，将模板创建能力下放给业务用户，释放平台的长尾价值。

## What Changes

- 新增**可视化模板编辑器**：拖拽式前端界面，支持表单步骤编排、数据步骤选择、section 布局设计，实时预览，自动生成符合 DSL v1 schema 的 YAML
- 新增**模板市场**：租户级和平台级的模板发布、发现、安装、评分机制，支持 builtin/tenant/community 三级模板分发
- 新增**模板蓝图系统**：预置常见报告类型的蓝图（如"设备日报"、"故障诊断"、"趋势分析"），用户基于蓝图快速派生模板，降低从零创建的认知负担
- 新增**模板导入/导出**：支持 `.template` 包格式（包含 DSL YAML + metadata + 依赖声明），便于跨环境迁移和社区分享
- 扩展**模板 fork 机制**：现有 `POST /{id}/fork` 扩展为市场安装路径，支持从市场一键 fork 到私有/租户空间

## Capabilities

### New Capabilities
- `visual-template-editor`: 可视化拖拽式模板编辑器前端，包含表单步骤编排、数据步骤配置、section 布局设计、实时预览和 DSL YAML 自动生成
- `template-marketplace`: 模板市场后端 API 与前端界面，支持模板发布、发现、搜索、评分、安装和版本管理
- `template-blueprint`: 模板蓝图系统，预置常见报告类型蓝图，支持从蓝图快速派生新模板

### Modified Capabilities
- `report-template-version-traceability`: 市场安装的模板需要追踪来源模板 ID 和版本，支持上游更新通知

## Impact

- **Frontend**: 新增模板编辑器页面（React + DnD 拖拽库）和市场浏览页面，约 15-20 个新组件
- **Backend API**: 新增 `/api/template-marketplace/` 路由组（发布、搜索、评分、安装），扩展现有 `/api/report-templates/` 路由
- **Database**: 新增 marketplace 相关表（template_listing、review、install_record）
- **Storage**: `.template` 包格式的序列化/反序列化
- **Dependencies**: 前端可能需要引入 DnD 库（如 `@dnd-kit`）；后端无新依赖
- **现有模板**: 8 个 builtin 模板不受影响，可作为蓝图的种子数据
