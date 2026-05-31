# DeerFlow CLI

DeerFlow CLI 是 DeerFlow AI 代理系统的命令行接口，提供完整的会话管理、持久化存储、流式响应和工具集成能力。采用**每个会话独立SQLite数据库**的架构设计，目的是为了解决全局锁竞争和状态污染问题。

## 核心特性

- **会话隔离**：每个会话拥有独立的SQLite数据库，无全局锁
- **检查点保留**：所有执行步骤持久化，支持精确回滚和行为审计
- **异步持久化**：后台线程处理文件写入，不阻塞主事件循环
- **多会话管理**：创建、切换、删除、归档、恢复会话
- **精确回滚**：支持按步骤回退和按检查点回退
- **会话导出**：导出为 Markdown 格式
- **会话搜索**：在所有会话中搜索关键词
- **文件管理**：支持文件上传、列出和删除
- **模型与技能**：动态切换模型，启用/禁用技能
- **运行模式**：计划模式、子代理模式开关
- **记忆系统**：查看和清空当前会话记忆

## 项目结构

```
cli/
├── cli.py              # 命令行接口
├── engine.py           # 核心引擎实现
├── session_store.py    # 会话存储实现
├── Dockerfile          # Docker构建文件
├── docker-compose.yaml # Docker Compose配置
└── __init__.py         # 模块初始化
```

运行时数据目录：

```
.deer-flow/
└── deerflow_sessions/
    ├── archive/                      # 归档会话目录
    ├── <session_id>.json             # 会话元数据文件
    ├── <session_id>_checkpoints.db   # 会话数据库
    └── <session_id>/                 # 导出文件目录
        └── export_<timestamp>.md     # 导出的Markdown文件
```

## 快速开始

### 前提条件

- Python 3.12+
- Docker 和 Docker Compose (可选)

### 本地运行

首先在项目根目录配置环境变量（包含模型、技能、MCP工具等配置）：

```bash
cd deer-flow
make config
```

**配置提示：**
- **模型配置**：参考config.example.yaml，配置在config.yaml中
- **技能配置**：在 `skills/` 目录下添加或修改技能配置文件
- **MCP工具配置**：参考extensions_config.example.json，配置在extensions_config.json中

然后安装 harness 包（开发模式）并运行 CLI：

```bash
cd backend/packages/harness
pip install -e .

cd ../../../cli
python cli.py
```

### Docker 运行

首先在宿主机配置环境变量（包含模型、技能、MCP工具等配置）：

```bash
cd deer-flow
make config
```

**配置提示：**
- **模型配置**：参考config.example.yaml，配置在config.yaml中
- **技能配置**：在 `skills/` 目录下添加或修改技能配置文件
- **MCP工具配置**：参考extensions_config.example.json，配置在extensions_config.json中

然后构建并运行容器：

```bash
cd cli
docker compose build
docker compose up -d
docker compose exec app bash -c "cd /deer-flow && python cli/cli.py"
```

## 使用说明

### 基本交互

启动后直接输入问题即可与AI代理对话：

```
======================================================================
DeerFlow Production Engine - 本地测试模式
======================================================================
Type !help to see all available commands | 输入 !help 查看所有可用命令
Type !multi to enter multi-line input mode | 输入 !multi 进入多行输入模式
======================================================================

[abcdef12] You: 你好
AI: 你好！我是DeerFlow AI助手，有什么可以帮助你的？

[Metrics] Tokens: 42 | Tool Calls: 0
```

### 命令列表

| 命令 | 说明 |
|------|------|
| `!new [id] [title]` | 创建新会话 |
| `!switch <id>` | 切换到指定会话 |
| `!delete session <id>` | 删除指定会话 |
| `!rename <title>` | 重命名当前会话 |
| `!archive <id>` | 归档指定会话 |
| `!archives` | 列出所有归档会话 |
| `!restore <id>` | 从归档恢复会话 |
| `!sessions` | 列出所有活动会话 |
| `!export` | 导出当前会话为Markdown |
| `!export_all` | 导出全部检查点为Markdown |
| `!search <keyword>` | 在所有会话中搜索关键词 |
| `!steps` | 查看当前会话的步骤列表（去重） |
| `!steps_all` | 查看全部检查点（包含无新内容的检查点） |
| `!back <N>` | 回退到第N步 |
| `!back_cp <N>` | 回退到第N个检查点 |
| `!upload <path>` | 上传文件到当前会话 |
| `!files` | 列出当前会话的所有上传文件 |
| `!delete <filename>` | 删除指定的上传文件 |
| `!models` | 列出所有可用模型 |
| `!use <model>` | 切换到指定模型 |
| `!skills` | 列出所有可用技能 |
| `!enable <skill>` | 启用指定技能 |
| `!disable <skill>` | 禁用指定技能 |
| `!plan on/off` | 开启/关闭计划模式 |
| `!subagent on/off` | 开启/关闭子代理委托 |
| `!memory` | 查看当前会话的记忆 |
| `!clear` | 清空当前会话的记忆 |
| `!multi` | 进入多行输入模式 |
| `!help` | 显示帮助信息 |
| `!exit` | 退出系统 |

### 多行输入模式

```
[abcdef12] You: !multi

[abcdef12] Multi-line Input Mode | 多行输入模式
Enter !end to finish multi-line input | 输入 !end 结束多行输入

这是第一行
这是第二行
这是第三行
!end

AI: 我收到了你的多行输入，内容是：
这是第一行
这是第二行
这是第三行
```

### 回滚功能

#### 按步骤回滚

```
[abcdef12] You: !steps

[Step List | 步骤列表]
  1. 你好
  2. 今天天气怎么样？
  3. 那明天呢？

[abcdef12] You: !back 2

[Rollback | 回溯] Reverted to step 2 | 已回退到步骤 2
Context | 上下文: 今天天气怎么样？

AI: 今天天气晴朗，气温25度，非常适合外出活动。
```

#### 按检查点回滚

```
[abcdef12] You: !steps_all

[All Checkpoints | 全部检查点] Total: 5

  [1] 12345678... | ts:1717042800 | ✓ New content | 有新内容
  [2] 23456789... | ts:1717042810 | ✓ New content | 有新内容
  [3] 34567890... | ts:1717042820 | ✗ No new content | 无新增
  [4] 45678901... | ts:1717042830 | ✓ New content | 有新内容
  [5] 56789012... | ts:1717042840 | ✓ New content | 有新内容

[abcdef12] You: !back_cp 4

[Rollback to Checkpoint | 回退到检查点] Index 4 | ID: 45678901
AI: 继续从该检查点分析...
```

## 架构设计

### 核心组件

1. **cli.py**：命令行接口，处理用户输入和命令解析
2. **engine.py**：核心引擎，管理会话生命周期和代理交互
3. **session_store.py**：会话存储，异步持久化会话元数据

### 关键设计

- **单例模式**：整个应用只有一个引擎实例
- **每会话独立数据库**：每个会话对应独立的SQLite文件，消除锁竞争
- **异步写入**：后台线程处理文件写入，不阻塞主线程
- **优雅关闭**：确保所有资源被正确释放

## 待办事项

- [ ] 解决全局锁竞争和状态污染问题

## 许可证

MIT License

---

**DeerFlow CLI** - DeerFlow AI 代理命令行工具