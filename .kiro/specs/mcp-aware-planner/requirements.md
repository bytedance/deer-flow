# Requirements Document

## Introduction

DeerFlow 的 planner 节点目前在制定研究计划时，没有考虑到系统中可用的 MCP 服务器工具。这导致生成的计划可能无法充分利用系统的全部能力。本功能旨在增强 planner 节点，使其在制定计划时能够考虑到可用的 MCP 工具，从而动态扩展 coder 和 researcher 的边界能力，生成更加有效和针对性的研究计划。

## Requirements

### Requirement 1

**User Story:** 作为一个研究人员，我希望 planner 能够了解系统中可用的 MCP 工具，以便生成更加有针对性和高效的研究计划。

#### Acceptance Criteria

1. WHEN planner 节点被调用时 THEN 系统 SHALL 收集所有可用的 MCP 服务器工具信息
2. WHEN planner 生成计划时 THEN 系统 SHALL 将 MCP 工具信息作为上下文提供给 LLM
3. WHEN planner 生成的计划包含使用特定 MCP 工具的步骤时 THEN 系统 SHALL 确保这些工具在执行阶段可用

### Requirement 2

**User Story:** 作为一个开发者，我希望 planner 能够根据研究主题智能地选择合适的 MCP 工具，以便生成最优的研究计划。

#### Acceptance Criteria

1. WHEN planner 生成计划时 THEN 系统 SHALL 分析研究主题与可用 MCP 工具的相关性
2. WHEN 某个 MCP 工具与研究主题高度相关时 THEN planner SHALL 优先考虑在计划中使用该工具
3. WHEN 生成的计划包含 MCP 工具使用建议时 THEN 系统 SHALL 在计划中包含工具的简要描述和使用方法

### Requirement 3

**User Story:** 作为一个用户，我希望能够看到 planner 是如何利用 MCP 工具来制定计划的，以便更好地理解和评估研究计划。

#### Acceptance Criteria

1. WHEN planner 生成包含 MCP 工具使用的计划时 THEN 系统 SHALL 在计划中明确标注哪些步骤将使用哪些 MCP 工具
2. WHEN 用户查看计划时 THEN 系统 SHALL 提供每个 MCP 工具的简要说明
3. WHEN 用户修改计划时 THEN 系统 SHALL 保留 MCP 工具相关的信息

### Requirement 4

**User Story:** 作为一个用户，我希望在前端界面上能够清晰地看到和理解 MCP 工具在研究计划中的应用，以便更好地评估和调整计划。

#### Acceptance Criteria

1. WHEN 用户查看研究计划时 THEN 系统 SHALL 在前端界面上以视觉化方式突出显示使用了 MCP 工具的步骤
2. WHEN 用户悬停在 MCP 工具名称上时 THEN 系统 SHALL 显示包含工具详细信息的悬浮卡片
3. WHEN 用户点击 MCP 工具名称时 THEN 系统 SHALL 展开显示工具的详细描述、参数和使用建议

### Requirement 5

**User Story:** 作为一个研究人员，我希望能够在前端界面上方便地编辑和调整使用 MCP 工具的计划步骤，以便根据我的需求优化研究计划。

#### Acceptance Criteria

1. WHEN 用户编辑研究计划时 THEN 系统 SHALL 提供可视化的 MCP 工具选择界面
2. WHEN 用户为步骤选择 MCP 工具时 THEN 系统 SHALL 提供结构化的参数编辑界面
3. WHEN 用户修改 MCP 工具参数时 THEN 系统 SHALL 提供参数验证和自动补全功能

### Requirement 6

**User Story:** 作为一个用户，我希望能够在研究步骤执行后，清晰地看到 MCP 工具的执行结果和贡献，以便评估工具的有效性。

#### Acceptance Criteria

1. WHEN 使用 MCP 工具的研究步骤执行完成后 THEN 系统 SHALL 在结果中标记哪些内容来自 MCP 工具
2. WHEN 用户查看执行结果时 THEN 系统 SHALL 提供工具执行的详细信息和统计数据
3. WHEN 用户评估研究结果时 THEN 系统 SHALL 允许用户对 MCP 工具的有效性进行评分和反馈