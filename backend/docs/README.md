# DeerFlow 后端文档

> **文档目的**：提供DeerFlow后端系统的文档索引和快速导航

## 快速链接

| 文档 | 描述 |
|----------|-------------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | 系统架构概述 |
| [API.md](API.md) | 完整API参考 |
| [CONFIGURATION.md](CONFIGURATION.md) | 配置选项 |
| [SETUP.md](SETUP.md) | 快速设置指南 |

## 功能文档

| 文档 | 描述 |
|----------|-------------|
| [FILE_UPLOAD.md](FILE_UPLOAD.md) | 文件上传功能 |
| [PATH_EXAMPLES.md](PATH_EXAMPLES.md) | 路径类型和使用示例 |
| [summarization.md](summarization.md) | 上下文摘要功能 |
| [plan_mode_usage.md](plan_mode_usage.md) | 计划模式与TodoList |
| [AUTO_TITLE_GENERATION.md](AUTO_TITLE_GENERATION.md) | 自动标题生成 |

## 开发

| 文档 | 描述 |
|----------|-------------|
| [TODO.md](TODO.md) | 计划功能和已知问题 |

## 入门指南

### 1. 新手入门

**如果你是DeerFlow新手**：
- 从 [SETUP.md](SETUP.md) 开始，了解快速安装步骤
- 阅读 [ARCHITECTURE.md](ARCHITECTURE.md) 理解系统架构
- 查看 [API.md](API.md) 了解API接口

**为什么这样安排**：
- SETUP.md 提供最少可行的安装步骤
- ARCHITECTURE.md 帮助理解系统整体设计
- API.md 是日常开发的参考手册

### 2. 配置系统

**如果你要配置系统**：
- 参考 [CONFIGURATION.md](CONFIGURATION.md) 了解所有配置选项
- 查看 [FILE_UPLOAD.md](FILE_UPLOAD.md) 配置文件上传
- 阅读 [PATH_EXAMPLES.md](PATH_EXAMPLES.md) 理解路径系统

**为什么需要这些文档**：
- CONFIGURATION.md 是配置的完整参考
- FILE_UPLOAD.md 是文件功能的详细说明
- PATH_EXAMPLES.md 提供实际使用示例

### 3. 理解架构

**如果你想深入理解架构**：
- 阅读 [ARCHITECTURE.md](ARCHITECTURE.md) 了解系统架构
- 查看 [middleware-execution-flow.md](middleware-execution-flow.md) 理解中间件执行流程
- 阅读 [rfc-create-deerflow-agent.md](rfc-create-deerflow-agent.md) 了解设计决策

**为什么这样设计**：
- ARCHITECTURE.md 提供高层架构视图
- middleware-execution-flow.md 详细说明执行流程
- RFC文档记录设计决策和权衡

### 4. 构建集成

**如果你要构建集成**：
- 查看 [API.md](API.md) 获取API参考
- 阅读 [PATH_EXAMPLES.md](PATH_EXAMPLES.md) 了解文件处理
- 参考 [CONFIGURATION.md](CONFIGURATION.md) 配置SDK

**为什么这些文档重要**：
- API.md 是集成的主要参考
- PATH_EXAMPLES.md 提供文件处理的实际示例
- CONFIGURATION.md 说明如何配置SDK行为

## 文档组织

```
docs/
├── README.md                  # 本文件 - 文档索引
├── ARCHITECTURE.md            # 系统架构
├── API.md                     # API参考
├── CONFIGURATION.md           # 配置指南
├── SETUP.md                   # 安装说明
├── FILE_UPLOAD.md             # 文件上传功能
├── PATH_EXAMPLES.md           # 路径使用示例
├── summarization.md           # 摘要功能
├── plan_mode_usage.md         # 计划模式功能
├── AUTO_TITLE_GENERATION.md   # 标题生成
├── TITLE_GENERATION_IMPLEMENTATION.md  # 标题实现细节
├── middleware-execution-flow.md         # 中间件执行流程
└── TODO.md                    # 路线图和问题
```

**为什么这样组织**：
- **分层结构**：从概述到详细，从通用到专用
- **功能导向**：按功能模块组织文档
- **用户路径**：不同的用户角色有不同的阅读路径

## 文档类型说明

### 概念性文档
- ARCHITECTURE.md：系统整体架构
- middleware-execution-flow.md：执行流程概念

### 参考性文档
- API.md：完整的API参考
- CONFIGURATION.md：所有配置选项

### 操作指南
- SETUP.md：安装和设置步骤
- PATH_EXAMPLES.md：实际使用示例

### 设计文档
- rfc-create-deerflow-agent.md：设计决策和权衡
- TODO.md：未来计划和已知问题

## 贡献指南

**如何贡献文档**：
1. 确保文档与代码同步
2. 使用清晰的结构和示例
3. 保持与现有文档风格一致
4. 更新相关索引和交叉引用

**文档质量标准**：
- 准确性：与实际实现一致
- 完整性：覆盖所有重要场景
- 可读性：清晰的结构和语言
- 实用性：提供可执行的示例
