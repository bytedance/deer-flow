# DeerFlow CLI

DeerFlow CLI 是 DeerFlow AI 代理系统的命令行接口，提供完整的会话管理、持久化存储、流式响应和工具集成能力。采用**每个会话独立SQLite数据库**的架构设计，旨在解决全局锁竞争和状态污染问题。

## 核心特性

- **会话隔离**：每个会话拥有独立的SQLite数据库，无全局锁
- **检查点保留**：所有执行步骤持久化，支持行为审计
- **异步持久化**：后台线程处理文件写入，不阻塞主事件循环
- **多会话管理**：创建、切换、删除、归档、恢复会话
- **会话导出**：导出为 Markdown 格式
- **会话搜索**：在所有会话中搜索关键词
- **文件管理**：支持文件上传、列出和删除
- **模型与技能**：动态切换模型，启用/禁用技能
- **运行模式**：计划模式、子代理模式开关
- **诊断系统**：工具调用分析、状态监控、递归限制设置
- **错误处理**：故障排查指引

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
- **模型配置**：参考 config.example.yaml，配置在 config.yaml 中
- **技能配置**：在 `skills/` 目录下添加或修改技能配置文件
- **MCP工具配置**：参考 extensions_config.example.json，配置在 extensions_config.json 中

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
- **模型配置**：参考 config.example.yaml，配置在 config.yaml 中
- **技能配置**：在 `skills/` 目录下添加或修改技能配置文件
- **MCP工具配置**：参考 extensions_config.example.json，配置在 extensions_config.json 中

然后构建并运行容器：

```bash
cd cli
docker compose build
docker compose up -d
docker compose exec app bash -c "cd /deer-flow && python cli/cli.py"
```

## 环境配置

### 离线环境

如遇 CLI 卡在 tiktoken 加载，可预缓存编码文件：

```bash
# 下载、计算 hash、重命名
mkdir -p ~/.tiktoken_cache
curl -L https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken \
  -o ~/.tiktoken_cache/cl100k_base.tiktoken
hash=$(sha1sum ~/.tiktoken_cache/cl100k_base.tiktoken | cut -d' ' -f1)
mv ~/.tiktoken_cache/cl100k_base.tiktoken ~/.tiktoken_cache/${hash}.tiktoken
```

Docker 挂载（在 docker-compose.yaml 添加）：
```yaml
volumes:
  - ${HOME}/.tiktoken_cache:/root/.tiktoken_cache:ro
environment:
  - TIKTOKEN_CACHE_DIR=/root/.tiktoken_cache
```

验证离线可用：
```bash
# 本地
TIKTOKEN_CACHE_DIR=~/.tiktoken_cache python -c "
import tiktoken
tiktoken.get_encoding('cl100k_base')
print('✓ 离线缓存可用')
"

# Docker
docker compose exec app python -c "
import tiktoken
tiktoken.get_encoding('cl100k_base')
print('✓ 离线缓存可用')
"
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

#### 会话管理

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

#### 调试诊断

| 命令 | 说明 |
|------|------|
| `!steps` | 查看当前会话的步骤列表（去重） |
| `!steps_all` | 查看全部检查点（包含无新内容的检查点） |
| `!diagnose` | 分析工具调用模式，检测潜在循环 |
| `!status` | 显示当前会话状态和运行时配置 |
| `!search <keyword>` | 在所有会话中搜索关键词 |

#### 文件管理

| 命令 | 说明 |
|------|------|
| `!upload <path>` | 上传文件到当前会话 |
| `!files` | 列出当前会话的所有上传文件 |
| `!delete <filename>` | 删除指定的上传文件 |

#### 模型与技能

| 命令 | 说明 |
|------|------|
| `!models` | 列出所有可用模型 |
| `!use <model>` | 切换到指定模型 |
| `!skills` | 列出所有可用技能 |
| `!enable <skill>` | 启用指定技能 |
| `!disable <skill>` | 禁用指定技能 |

#### 运行模式

| 命令 | 说明 |
|------|------|
| `!plan on/off` | 开启/关闭计划模式 |
| `!subagent on/off` | 开启/关闭子代理委托 |
| `!recursion_limit <N>` | 设置递归限制（默认：1000） |

#### 记忆系统

| 命令 | 说明 |
|------|------|
| `!memory` | 查看当前会话的记忆 |
| `!clear` | 清空当前会话的记忆 |

#### 其他

| 命令 | 说明 |
|------|------|
| `!export` | 导出当前会话为Markdown |
| `!export_all` | 导出全部检查点为Markdown |
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

### 诊断功能

#### 工具调用诊断

```
[abcdef12] You: !diagnose

[Tool Call Diagnostics | 工具调用诊断]
  Session: abcdef12
  Total checkpoints: 42

[Tool Call Frequency Comparison | 工具调用频率对比]
  Tool Name                                | Unique   | Raw (with dup)  | Ratio
  ----------------------------------------+----------+-----------------+--------
  Read                                     | 15       | 120             | 8.0x
  Bash                                     | 8        | 64              | 8.0x
  Grep                                     | 3        | 24              | 8.0x

[Checkpoint Density Analysis | 检查点密度分析]
  Unique tool calls: 26
  Raw occurrences across all checkpoints: 208
  Average duplications per unique call: 8.0x
  ⚠️  High duplication - each tool call appears in many checkpoints
      This is normal for long-running sessions with subagents

[Potential Loop Detection | 潜在循环检测]
  ⚠️  Read: 5 consecutive calls (potential loop)
```

#### 会话状态

```
[abcdef12] You: !status

[Session Status | 会话状态]
  Session ID: abcdef12

[Runtime Settings | 运行时配置]
  Model: claude-opus-4-7
  Subagent: ✓ Enabled
  Plan Mode: ✗ Disabled
  Thinking: ✓ Enabled

[Session Metrics | 会话指标]
  Checkpoints: 42
  Recursion Limit: 1000
  ⚠️  Approaching recursion limit (42/1000)
```

### 错误处理

当检测到Error时，系统会自动显示：

```
[Critical Error | 严重错误] Error ...

[Traceback | 堆栈跟踪]
...

[Session Status at Error | 错误发生时的会话状态]
  Subagent: ✓ Enabled
  Plan Mode: ✗ Disabled

[Troubleshooting | 故障排除]
  1. 使用 !status 查看完整会话状态
  2. 使用 !diagnose 分析工具调用模式
  3. 使用 !steps_all 查看已保存的检查点
  4. 使用 !export_all 导出完整检查点历史
  5. Subagent 当前已启用 - 尝试关闭: !subagent off
```

### 检查点警告

当检查点数量接近递归限制时：

```
[WARNING] Checkpoints: 850/1000 - Getting close to limit

⚠️  [CRITICAL] Checkpoints: 920/1000 - Approaching recursion limit!
 Subagent is enabled - consider disabling with: !subagent off
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
- **诊断能力**：工具调用模式分析，辅助问题排查

## 许可证

MIT License

---

**DeerFlow CLI** - DeerFlow AI 代理命令行工具
