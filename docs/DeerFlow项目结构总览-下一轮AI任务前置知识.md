# DeerFlow 项目结构总览
## 下一轮AI任务的前置知识文档

## 1. 项目定位

**DeerFlow** 是字节跳动开源的基于 **LangGraph** 的超级代理（Super Agent）编排框架。

### 核心价值
- 通过编排**子代理**、**记忆**、**沙箱**完成复杂任务
- 支持多模型、多渠道、多技能的扩展
- 提供 Web、IM、CLI 等多种交互方式

### 技术定位
- **后端**: Python 3.12+ + LangChain + LangGraph + FastAPI
- **前端**: Next.js 16 + React 19 + TypeScript 5.8
- **架构**: 四层架构（用户交互层、接入层、核心引擎层、能力层）

---

## 2. 系统架构概览

### 2.1 四层架构

```
┌─────────────────────────────────────────────────────┐
│  用户交互层                                            │
│  - Web前端 (Next.js :3000)                           │
│  - IM渠道 (飞书/Slack/Telegram)                      │
│  - CLI客户端 (DeerFlowClient)                        │
├─────────────────────────────────────────────────────┤
│  接入层                                                │
│  - Nginx反向代理 (:2026)                              │
│  - Gateway API (FastAPI :8001)                        │
│  - LangGraph Server (:2024)                           │
├─────────────────────────────────────────────────────┤
│  核心引擎层                                            │
│  - Lead Agent (make_lead_agent)                        │
│  - 中间件链 (12个中间件)                             │
│  - ThreadState (状态管理)                             │
│  - SubagentExecutor (双线程池)                        │
├─────────────────────────────────────────────────────┤
│  能力层                                                │
│  - 工具集 (builtins + MCP + community)                  │
│  - 技能系统 (public + custom)                          │
│  - 记忆系统 (updater + queue)                          │
│  - 沙箱系统 (local + docker)                           │
│  - 配置系统 (app + extensions)                          │
└─────────────────────────────────────────────────────┘
```

### 2.2 端口分配

| 服务 | 端口 | 说明 |
|------|------|------|
| Nginx | 2026 | 统一入口 |
| Gateway API | 8001 | REST API |
| LangGraph Server | 2024 | Agent运行时 |
| Frontend | 3000 | Web界面 |

---

## 3. 目录结构详解

### 3.1 顶层目录

```
deer-flow-main/
├── backend/              # 后端服务
│   ├── app/              # 应用层 (app.*)
│   │   ├── gateway/       # FastAPI Gateway API
│   │   └── channels/      # IM渠道集成
│   ├── packages/
│   │   └── harness/       # 可发布的Agent框架
│   │       └── deerflow/    # 核心包 (deerflow.*)
│   ├── tests/             # 测试套件
│   └── docs/              # 后端文档
├── frontend/             # 前端应用
│   └── src/
│       ├── app/          # Next.js App Router
│       ├── components/   # React组件
│       └── core/          # 核心业务逻辑
├── skills/               # 技能目录
│   ├── public/          # 公共技能（已提交）
│   └── custom/          # 自定义技能（gitignore）
├── docker/               # Docker配置
├── scripts/             # 项目脚本
├── docs/                # 文档目录
└── plan/                # 计划文档（新增）
```

### 3.2 Harness 核心目录

```
packages/harness/deerflow/
├── agents/              # Agent系统
│   ├── lead_agent/      # 主导代理
│   │   ├── agent.py     # Agent工厂
│   │   └── prompt.py    # 系统提示词
│   ├── middlewares/     # 12个中间件
│   │   ├── thread_data_middleware.py
│   │   ├── memory_middleware.py
│   │   ├── sandbox_middleware.py
│   │   ├── title_middleware.py
│   │   ├── clarification_middleware.py
│   │   └── ...
│   ├── memory/          # 记忆系统
│   │   ├── updater.py    # LLM驱动更新
│   │   ├── queue.py      # 防抖队列
│   │   └── prompt.py
│   └── thread_state.py  # 线程状态定义
├── sandbox/             # 沙箱系统
│   ├── local/           # 本地文件系统
│   ├── sandbox.py       # 抽象接口
│   └── tools.py         # 沙箱工具
├── subagents/           # 子代理系统
│   ├── builtins/        # 内置代理
│   ├── executor.py      # 执行器（双线程池）
│   └── registry.py      # 代理注册表
├── tools/               # 工具系统
│   └── builtins/        # 内置工具
├── models/              # 模型工厂
│   └── factory.py       # create_chat_model()
├── skills/              # 技能系统
│   ├── loader.py        # 技能加载
│   ├── parser.py        # SKILL.md解析
│   └── types.py         # 类型定义
├── mcp/                 # MCP集成
│   ├── client.py        # MCP客户端
│   └── tools.py         # MCP工具
├── community/           # 社区工具
│   ├── tavily/          # 网络搜索
│   ├── jina_ai/         # 网页抓取
│   └── aio_sandbox/      # Docker沙箱
├── config/              # 配置系统
├── guardrails/          # 安全护栏
├── reflection/          # 动态加载
├── runtime/             # 运行时
└── utils/               # 工具函数
```

### 3.3 前端核心目录

```
frontend/src/
├── app/                 # Next.js页面路由
│   ├── api/             # API路由
│   └── workspace/       # 工作区页面
├── components/          # React组件
│   ├── ui/              # Shadcn UI组件
│   ├── workspace/      # 工作区组件
│   └── landing/         # 落地页组件
├── core/                # 核心业务逻辑
│   ├── threads/         # 线程管理
│   ├── api/             # API客户端
│   ├── skills/          # 技能管理
│   ├── memory/          # 记忆系统
│   └── ...
├── hooks/               # 自定义Hook
└── lib/                 # 工具库
```

---

## 4. 关键设计模式

### 4.1 Harness/App 分离

```
依赖规则：
┌─────────────────┐
│  App (app.*)     │
└────────┬────────┘
         │
         │ 可以导入
         ↓
┌─────────────────┐
│ Harness        │
│ (deerflow.*)   │
└─────────────────┘
         │
         │ 禁止导入
         ✗

目的：Harness是可复用框架，App是特定应用
```

### 4.2 中间件链（12个，固定顺序）

```
执行顺序：
1. ThreadDataMiddleware
2. UploadsMiddleware
3. SandboxMiddleware
4. DanglingToolCallMiddleware
5. GuardrailMiddleware
6. SummarizationMiddleware (可选)
7. TodoListMiddleware (可选)
8. TitleMiddleware
9. MemoryMiddleware
10. ViewImageMiddleware (条件)
11. SubagentLimitMiddleware (条件)
12. ClarificationMiddleware
```

### 4.3 子代理系统

```
双线程池设计：
- 调度池 (3 workers) - 控制并发
- 执行池 (3 workers) - 实际执行

内置代理：
- general-purpose (通用)
- bash (命令专家)

限制：
- 最大并发数：3
- 超时：15分钟
```

### 4.4 记忆系统

```
三组件架构：
1. MemoryMiddleware - 拦截消息
2. Update Queue - 30秒防抖
3. MemoryUpdater - LLM驱动更新

数据结构：
- UserContext (workContext, personalContext, topOfMind)
- History (recentMonths, earlierContext, longTermBackground)
- Facts (带category, confidence, timestamp)
```

---

## 5. 技术栈总结

### 5.1 后端技术

```
核心框架：
- Python 3.12+
- LangChain + LangGraph
- FastAPI

依赖管理：
- pnpm 10.26.2
- uv (推荐)

数据存储：
- SQLite / PostgreSQL
- JSON文件 (记忆)
```

### 5.2 前端技术

```
核心框架：
- Next.js 16
- React 19
- TypeScript 5.8

UI组件：
- Shadcn/ui
- Tailwind CSS 4

状态管理：
- TanStack Query
- Zustand
```

### 5.3 集成技术

```
容器化：
- Docker
- Nginx

协议：
- MCP (Model Context Protocol)
- SSE (Server-Sent Events)
- WebSocket
```

---

## 6. 配置文件

### 6.1 主配置文件

**位置**: `config.yaml` (项目根目录)

**主要配置**：
```yaml
models:              # 模型配置
tools:               # 工具配置
sandbox:             # 沙箱配置
skills:              # 技能配置
memory:              # 记忆配置
subagents:           # 子代理配置
title:               # 标题生成配置
summarization:       # 摘要配置
```

### 6.2 扩展配置文件

**位置**: `extensions_config.json` (项目根目录)

**主要配置**：
```json
{
  "mcpServers": {},  // MCP服务器
  "skills": {}        // 技能启用状态
}
```

---

## 7. 关键代码路径

### 7.1 Agent创建流程

```
入口：langgraph.json
  ↓
make_lead_agent()
  → agents/lead_agent/agent.py
  → 创建模型：models/factory.py
  → 加载工具：tools/__init__.py
  → 构建中间件：_build_middlewares()
  → 应用提示词：prompt.py
```

### 7.2 技能加载流程

```
入口：Gateway API或DeerFlowClient
  ↓
load_skills()
  → skills/loader.py
  → 扫描public/和custom/
  → 解析SKILL.md
  → 从extensions_config.json读取启用状态
  → 注入到系统提示词
```

### 7.3 中间件执行流程

```
请求进入：
  → before_model() (中间件1-12)
  → LLM调用
  → after_model() (中间件12-1)
  → 响应返回
```

---

## 8. 核心设计决策

### 8.1 为什么用LangGraph？

```
优势：
- 强大的状态图模型
- 检查点原生支持
- 流式响应
- 生态集成

代价：
- 学习曲线陡
- 需要理解状态图概念
```

### 8.2 为什么双线程池？

```
设计目的：
- 调度池：控制并发数
- 执行池：实际执行

好处：
- 解耦调度和执行
- 防止资源耗尽
- 统一管理生命周期
```

### 8.3 为什么LLM驱动记忆？

```
优势：
- 理解语义
- 提取隐含信息
- 自动分类

代价：
- LLM调用成本
- 异步更新延迟
```

---

## 9. 扩展点总结

### 9.1 可扩展的部分

```
1. 自定义模型适配器
   → 实现BaseModel接口
   → 配置到config.yaml

2. 自定义工具
   → Python函数
   → 配置到config.yaml

3. 自定义技能
   → 创建SKILL.md
   → 添加scripts/

4. 自定义中间件
   → 实现AgentMiddleware
   → 注入到_build_middlewares()

5. 自定义渠道
   → 实现Channel基类
   → 注册到ChannelManager
```

### 9.2 配置驱动的扩展

```
配置驱动的设计：
→ 模型通过config.yaml配置
→ 工具通过config.yaml配置
→ 技能通过extensions_config.json配置

好处：
→ 不需要改代码
→ 运行时可以更改
→ 便于实验和调试
```

---

## 10. 给下一轮AI的建议

### 10.1 代码阅读优先级

```
高优先级（必须理解）：
1. agents/lead_agent/agent.py - Agent创建
2. agents/middlewares/ - 中间件系统
3. subagents/executor.py - 子代理执行
4. skills/loader.py - 技能加载
5. models/factory.py - 模型工厂

中优先级（重要理解）：
6. agents/memory/updater.py - 记忆更新
7. sandbox/sandbox.py - 沙箱接口
8. tools/__init__.py - 工具加载
9. gateway/app.py - API入口
10. config/ - 配置系统

低优先级（了解即可）：
11. channels/ - IM渠道
12. utils/ - 工具函数
13. reflection/ - 动态加载
```

### 10.2 关键概念清单

```
必须理解的概念：
- LangGraph状态图
- 中间件模式
- 工厂模式
- 适配器模式
- 检查点机制
- SSE流式响应
- 虚拟路径系统
- 双线程池设计
- LLM驱动的记忆
- SKILL.md格式
- MCP协议
```

### 10.3 代码组织原则

```
依赖规则：
→ App可以导入Harness
→ Harness禁止导入App
→ 通过test_harness_boundary.py强制执行

命名规范：
→ deerflow.* - Harness层
→ app.* - App层

配置优先级：
1. 显式config_path
2. 环境变量
3. 当前目录config.yaml
4. 父目录config.yaml
```

---

## 11. 常见命令

```bash
# 开发环境
make dev              # 启动所有服务
cd backend && make dev  # 只启动后端

# 测试
make test             # 运行所有测试

# 代码检查
make check            # 检查系统要求
make format           # 格式化代码
make lint             # 代码检查
```

---

## 12. 文档衔接说明

### 12.1 已有学习文档

在 `docs/` 目录下有20篇学习文档：
- 08-13：架构与核心概念（已基于实际代码更新）
- 14-20：沙箱、检查点、设计模式、面试、扩展等

### 12.2 使用建议

```
对于下一轮AI任务：

1. 先读本文档（10分钟）
   → 了解整体架构
   → 理解目录结构
   → 掌握关键设计

2. 再读相关文档（按需）
   → 需要深入哪个模块
   → 就读对应的docs文档

3. 结合源码阅读
   → 按优先级阅读代码
   → 参考文档中的解释
```

---

**文档名称**: `DeerFlow项目结构总览-下一轮AI任务前置知识.md`

**位置**: `/data/deer-flow-main/docs/DeerFlow项目结构总览-下一轮AI任务前置知识.md`

这个文档总结了我刚刚梳理的项目结构，包含了：
- 四层架构
- 目录详解
- 关键设计模式
- 技术栈总结
- 扩展点说明

下一轮AI可以基于这个文档快速理解项目，然后再深入阅读具体的源码文件。
