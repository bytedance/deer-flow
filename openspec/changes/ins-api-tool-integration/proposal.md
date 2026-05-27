## Why

INS 系统中已有完整的设备台账、测点定义、振动频谱、历史报警和同类对标数据（通过 REST API 暴露），但 DeerFlow 的诊断 Agent 在做故障分析时无法直接获取这些数据。当前 Agent 只能依赖 LLM 的通用知识"猜"诊断结论，或在对话中要求用户手动贴入数据，导致诊断准确率低、交互效率差。

需要将 INS API 封装为 DeerFlow 可调用的工具，让 Agent 在诊断时能实时查询设备上下文，从"猜测"升级为"数据驱动推理"。

## What Changes

- **新增 INS 工具集**：封装 5 个核心 INS REST API 为 DeerFlow 工具（设备详情、测点趋势、振动频谱、历史报警、同类对标），支持 Agent 在对话中按需调用
- **三种集成模式并存**：
  - 社区工具（`deerflow/community/ins/`）：轻量级 Python 工具，直接在 `config.yaml` 的 `tools:` 段注册，快速上线
  - MCP Server（可选）：标准化协议封装，支持跨平台复用，适合需要与其他 Agent 框架共享的场景
  - Skill 内嵌（SOUL.md 引用）：在诊断 Skill 的工作流描述中声明数据获取步骤，引导 Agent 按序调用工具
- **模板可配置化**：报告模板（`report_templates/`）支持声明所需的 INS 数据字段，运行时自动注入到 Agent 上下文
- **平滑迁移**：复用现有的 `http_connector_tool` 基础设施（租户隔离、认证、缓存、重试），不破坏现有业务
- **Agent 自由选用**：所有 Agent（lead_agent、monitoring-analysis、device-diagnosis、trend-report）均可通过 `get_available_tools()` 获取 INS 工具，无需硬编码依赖

## Capabilities

### New Capabilities

- `ins-tools`: INS REST API 工具集封装，包含 5 个核心工具（设备详情、测点趋势、振动频谱、历史报警、同类对标），支持租户隔离、认证、缓存
- `ins-template-integration`: 报告模板声明式 INS 数据绑定，模板运行时自动将所需 INS 数据注入 Agent 上下文
- `ins-skill-enhancement`: 诊断 Skill 增强，在 SOUL.md 中声明 INS 数据获取工作流，引导 Agent 按标准流程诊断

### Modified Capabilities

（无现有规格变更，全部为新增能力）

## Impact

- **后端 Harness 层** (`packages/harness/deerflow/community/ins/`)：新增 INS 工具集模块（provider + 5 个工具函数 + 配置模型）
- **后端配置** (`config.yaml`)：新增 `http_connectors` 段用于 INS API 端点配置（复用现有 `HttpConnectorConfig` 模型）
- **后端工具注册** (`tools/tools.py`)：INS 工具通过 `http_connector_tool` 或直接注册为 builtin，无需修改核心逻辑
- **Skills 目录** (`skills/public/`)：更新 `device-diagnosis`、`monitoring-analysis`、`trend-report` 等工业 Skill 的 SOUL.md，声明 INS 数据获取步骤
- **前端 GenUI** (`frontend/src/components/genui/`)：现有 `DeviceSelectorBlock` 已对接 INS 设备树，无需修改；报告模板编辑器新增 INS 数据字段选择器
- **报告模板平台** (`core/report-templates/`)：DSL 扩展支持声明 `ins_data_requirements` 字段
- **依赖**：复用现有 `httpx`，无新增外部依赖
