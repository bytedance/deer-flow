# Tool 与 Skill 架构边界

本文档定义 DeerFlow 项目中 **Tool** 和 **Skill** 的职责边界、判断标准和协作模式。

## 概念定义

```
┌─────────────────────────────────────────────────────────────────┐
│                         Tool (工具)                              │
│                                                                  │
│  LangChain `@tool` / `StructuredTool`，由后端运行时直接装配和执行    │
│                                                                  │
│  能访问:                                                         │
│  ├─ RunnableConfig (tenant_id, user_id, 权限标记)                │
│  ├─ Service 层 (ClosureService, ReportService, ...)              │
│  ├─ DB Session / ORM Models                                     │
│  ├─ 领域模型 (状态机、Pydantic Schema、枚举)                      │
│  └─ 运行时对象 (SkillStorage, 沙箱路径, 中间件)                    │
│                                                                  │
│  常见装配来源:                                                    │
│  ├─ `backend/packages/harness/deerflow/tools/builtins/`          │
│  ├─ `backend/packages/harness/deerflow/community/`               │
│  ├─ `config.yaml -> tools[].use` 指向的 Python Tool               │
│  ├─ `deerflow.integrations.tools.tool_builder` 构造的集成 Tool     │
│  └─ `extensions_config.json` 中启用的 MCP tools                  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                        Skill (技能)                               │
│                                                                  │
│  `SKILL.md` 指令 + 可选脚本/模板/参考资料组成的能力包              │
│                                                                  │
│  运行时可用资产:                                                  │
│  ├─ Skill 元信息（name / description / location）                 │
│  ├─ 模板、参考资料、产物目录                                       │
│  ├─ 命令行参数（当脚本被执行时，由 Agent/Tool 传入）               │
│  ├─ 环境变量 (`INS_ACCESS_TOKEN` 等，由运行时注入)                 │
│  ├─ 文件系统 (`/mnt/user-data/`, `/mnt/skills/`)                 │
│  └─ 外部 API（InS、CRM、第三方服务）                              │
│                                                                  │
│  受保护源码:                                                     │
│  ├─ `/mnt/skills/**/SKILL.md`                                    │
│  └─ `/mnt/skills/**/*.py`                                        │
│                                                                  │
│  不能访问:                                                       │
│  ├─ RunnableConfig (无法获取 tenant_id / user_id)                │
│  ├─ 项目内部 Python 对象 (Service, DB Session, ORM)              │
│  └─ 领域模型和状态机                                             │
│                                                                  │
│  存放位置: `skills/public/`（平台内置，只读）                      │
│           `skills/custom/`（用户自定义，可编辑/删除）              │
│                                                                  │
│  挂载路径: /mnt/skills/{category}/{name}/                        │
└─────────────────────────────────────────────────────────────────┘
```

## 判断标准

### 决策流程图

```
需要新增一个能力
        │
        ▼
┌──────────────────┐    是    ┌──────┐
│ 需要 tenant_id /  │────────▶│ Tool │
│ user_id 做隔离？  │         └──────┘
└──────────────────┘
        │ 否
        ▼
┌──────────────────┐    是    ┌──────┐
│ 需要访问内部      │────────▶│ Tool │
│ Service/DB/ORM？  │         └──────┘
└──────────────────┘
        │ 否
        ▼
┌──────────────────┐    是    ┌──────┐
│ 需要基于运行时    │────────▶│ Tool │
│ 权限做过滤？       │         └──────┘
└──────────────────┘
        │ 否
        ▼
┌──────────────────┐    是    ┌──────┐
│ 需要被多个 Agent  │────────▶│Skill │
│ 共享且无状态？     │         └──────┘
└──────────────────┘
        │ 否
        ▼
┌──────────────────┐    是    ┌──────┐
│ 包含重计算 /      │────────▶│Skill │
│ 多步骤数据处理？   │         └──────┘
└──────────────────┘
        │ 否
        ▼
┌──────────────────┐    是    ┌──────┐
│ 需要用户可定制    │────────▶│Skill │
│ 或可独立部署？     │         └──────┘
└──────────────────┘
        │ 否
        ▼
   根据接口粒度判断：
   - 窄接口(少量参数) → Tool
   - 宽接口(复杂流程) → Skill
```

### 速查表

| 条件 | Tool | Skill |
|------|:----:|:-----:|
| 需要从 `RunnableConfig` 解析 `tenant_id` / `user_id` | ✅ | ❌ |
| 需要访问 Service 层 (`ClosureService`, `ReportService`) | ✅ | ❌ |
| 需要 DB Session 或 ORM Model | ✅ | ❌ |
| 需要基于运行时权限 (`is_superadmin`, `is_tenant_admin`) 过滤数据 | ✅ | ❌ |
| 需要领域模型校验 (状态机、Pydantic Schema、枚举) | ✅ | ❌ |
| 需要被中间件拦截 (如 `ClarificationMiddleware`) | ✅ | ❌ |
| 纯 HTTP 调用外部 API（无 tenant 隔离要求） | ✅* | ✅ |
| 需要 tenant 隔离的外部 API 调用 | ✅ | ❌ |
| 重计算 / 批量数据处理 | ❌ | ✅ |
| 需要以 `SKILL.md` + 脚本/模板/参考资料的形式沉淀能力 | ❌ | ✅ |
| 用户可 fork / 编辑 / 安装自己的版本 | ❌ | ✅ |
| 跨多个 Agent 共享的脚本逻辑 | ❌ | ✅ |
| 包含参考文档或模板文件 | ❌ | ✅ |

> \* 社区工具 (Tavily, Jina 等) 以 Tool 实现是为了统一从 `config.yaml` 解析 API key，避免凭据散落在 Skill 脚本中。如果不需要集中管理凭据，纯外部 API 调用也可以做 Skill。

## 安全红线

Tool 的 **核心安全价值** 是：`tenant_id` 和 `user_id` 从 `RunnableConfig` 解析，**不由 LLM 传入**。

```python
# ✅ 正确 — Tool 内部解析身份
@tool("list_closure_tickets")
async def list_closure_tickets(device_id=None, status=None):
    cfg = get_config()["configurable"]
    tenant_id = cfg["tenant_id"]      # ← 系统注入，LLM 不知道
    user_id = cfg["user_id"]          # ← 系统注入
    return await service.list_tickets(tenant_id=tenant_id, ...)

# ❌ 错误 — 如果用 Skill 脚本，LLM 自己传身份参数
# python list_tickets.py --tenant-id "xxx" --user-id "yyy"
#                         ↑ LLM 填的，可被 prompt injection 篡改
```

**凡是涉及租户隔离、用户权限、数据归属的操作，必须是 Tool。**

## 运行时可见性过滤

Tool 或 Skill 是否“存在于仓库中”，不等于它会出现在某次 Agent 运行里。当前框架会在运行时做二次过滤，`注册存在 ≠ 当前 Agent 可见`。

### Tool 可见性

- `get_available_tools(...)` 会先按 `tool_groups` 过滤 `config.tools`
- 当本地沙箱禁用 host bash 时，对应 Tool 不会暴露给 Agent
- 报告类 Tool 会按 `agent_config.executor_type` 在 DSL / direct 两套路由间切换
- 只有 `subagent_enabled=True` 时才注入 subagent tools
- 只有模型支持 vision 时才注入 `view_image_tool`
- MCP tools 会继续经过 `extensions_config.json`、tenant MCP 覆盖配置、`mcp_servers` 白名单过滤
- `data_tools` 由 agent config 额外挂载，`exclude_tools` 在最后一层剔除

### Skill 可见性

- Skill 列表会先由 `SkillStorage.load_skills(enabled_only=True)` 与 `extensions_config.json` 合并启用状态
- `public` / `custom` skill 若未显式声明，当前实现默认启用；tier 默认为 `foundation`
- Agent prompt 只会注入 `agent_config.skills` 允许的 skill 集合；未被注入的 skill 对该 Agent 等价于不可见

### 设计含义

- “把能力放进 `skills/` 或注册到 `config.yaml`” 只是候选集，不是最终暴露面
- 需要按 Agent、租户、模型能力、沙箱策略切换的“是否可见”问题，应视为运行时装配问题，而不是静态目录问题

## Skill Source Protection

在 DeerFlow 中，Skill 是**可挂载、可执行、可引用的系统资产**，但不是可被 Agent 任意读取和转述的源码资产。当前实现对 Skill 源码保护采用三层约束：

1. **Prompt 层**：系统提示明确禁止读取、展示、输出 `/mnt/skills/` 下的 `SKILL.md` 和 `.py` 源码
2. **Sandbox / Tool 层**：`read_file` 与 shell / python 源码读取路径会拦截 `/mnt/skills/**/SKILL.md` 与 `/mnt/skills/**/*.py`
3. **审计层**：中间件会将读取 Skill 源码的命令模式视为高风险行为

可以做的事：

- 执行 Skill 脚本，例如由 Tool 或 Agent 触发 `python /mnt/skills/.../scripts/*.py`
- 读取 Skill 运行产物，例如写入 `/mnt/user-data/outputs/` 的结果文件
- 使用 Skill 的元信息（name / description）做能力发现与选择

不能做的事：

- 直接 `read_file /mnt/skills/**/SKILL.md`
- 直接 `cat` / `head` / `open()` `/mnt/skills/**/*.py`
- 向用户展示或转述 Skill 内部实现源码与受保护指令正文

因此，**Skill 的“可执行”不等于“源码可读”**。如果某项能力需要让 Agent 理解，应暴露摘要化的元信息或受控接口，而不是把 Skill 源码本身作为上下文数据面开放。

## 典型示例

### 示例 1：闭环工单 CRUD → Tool

```
list_closure_tickets
├─ 依赖: RunnableConfig → tenant_id, user_id, is_tenant_admin
├─ 依赖: ClosureService → ClosureRepository → DB Session
├─ 依赖: 权限三元组 [CLOSURE_READ, CLOSURE_WRITE, CLOSURE_VERIFY]
└─ 判定: Tool (三个内部依赖全部命中)
```

### 示例 2：监测数据获取 → Tool + Skill 分层

```
monitoring_get_trend (Tool)          monitoring-data (Skill)
├─ 单点查询                           ├─ 批量获取
├─ 需要 AuthContext                   ├─ 需要 INS_ACCESS_TOKEN 环境变量
│  (tenant_id, user_id, token)       ├─ positionType 路由逻辑
├─ 返回结构化数据给 LLM 推理           ├─ 波形/频谱数据合成
└─ 适用: Agent 简单问答               ├─ 适用: 监测分析完整流程
                                      └─ 可 fork 定制
```

两者的关系：**Tool 提供安全的数据入口，Skill 做重数据处理**。Agent 用 Tool 获取上下文，用 Skill 跑分析流程。

### 示例 3：CRM 分析 → Tool + Skill 分层

```
crm_query_outbound (Tool)            crm-analyst (Skill)
├─ 单次查询                           ├─ 多步骤分析流程
├─ 需要 AuthContext                   ├─ 异常检测算法
├─ tenant 隔离的 API 调用             ├─ 报告生成模板
└─ 适用: "查一下最近的出库"            ├─ 适用: "生成 CRM 综合分析报告"
                                      └─ 可独立部署
```

### 示例 4：报告生成 → 两套执行路径

```
DSL 路径 (Tool 链)                   Direct 路径 (Tool → Skill)
├─ report_template_prepare_run       ├─ report_direct_execute
├─ report_template_run_data_steps    │   └─ 由后端 Tool 编排 Skill 脚本:
├─ report_template_submit_step       │       /mnt/skills/custom/daily-report/
├─ ... (8 个 runtime tools)          │       /mnt/skills/custom/weekly-report/
├─ DSL 状态机驱动                     │       /mnt/skills/custom/monthly-report/
└─ 适用: 自定义报告模板               └─ 适用: 标准日报/周报/月报
```

两者并存的原因：
- **DSL 路径** — 灵活，用户可以自定义报告模板和步骤
- **Direct 路径** — 简洁，标准报告由 Tool 在后端直接编排 Skill 脚本，减少 LLM 轮次

### 示例 5：纯 Skill — 指令 / 模板 / 通用能力

```
deep-research (Skill)                frontend-design (Skill)
├─ 多轮搜索 + 分析方法                ├─ UI 设计指南
├─ 指令为主，可配合脚本/检索            ├─ 参考文档 + 模板
├─ 无内部对象依赖                     ├─ 无内部对象依赖
└─ 判定: Skill                       └─ 判定: Skill
```

## Tool ↔ Skill 协作模式

```
                      ┌──────────────┐
                      │   Agent      │
                      │  (SOUL.md)   │
                      └──────┬───────┘
                             │
            ┌────────────────┼────────────────┐
            ▼                ▼                ▼
      ┌──────────┐    ┌──────────┐    ┌──────────┐
      │  Tool    │    │  Tool    │    │  Skill   │
      │ (上下文)  │    │ (渲染)   │    │ (指令/资产)│
      └──────────┘    └──────────┘    └──────────┘
            │                ▲                │
            │                │                │
            ▼                │                ▼
      ┌──────────┐          │         ┌──────────────┐
      │ 内部服务  │          │         │  /mnt/skills/ │
      │ Service  │          │         │  scripts/     │
      │ DB/ORM   │          │         │  templates/   │
      │          │          │         │  外部 API     │
      └──────────┘          │         └──────┬───────┘
                            │                │
                            └────────────────┘
                            render_ui / present_files
                            将 Skill 产出渲染到前端
```

典型流程：
1. **Tool** 获取上下文 (`resolve_machine_context`, `monitoring_get_trend`)
2. **Skill** 做重计算 (`monitoring-data` → `monitoring-analysis`)
3. **Tool** 渲染结果 (`render_charts_file`, `present_files`)

## 新增能力 Checklist

### 选 Tool 路径时确认：

- [ ] 实现了 `@tool` 或 `StructuredTool`
- [ ] 安全身份从 `RunnableConfig` / `AuthContext` 解析，不由 LLM 传参
- [ ] 按实际装配路径注册：`tools/builtins/__init__.py`、`config.yaml tools[].use`、`tool_builder.py` 或 MCP 配置
- [ ] 数据类 Tool 优先返回结构化结果（JSON / envelope）
- [ ] 交互类 Tool（如 `present_files`、`render_ui`）可返回 `Command` / `ToolMessage`
- [ ] 对外暴露的失败路径应 fail-closed，不把未处理异常直接泄露给 Agent 主流程

### 选 Skill 路径时确认：

- [ ] 创建了 `SKILL.md`（含 frontmatter: `name`, `description`）
- [ ] 如需可执行脚本，放在 `scripts/`；模板/参考资料放在 `templates/`、`references/`、`assets/`
- [ ] 敏感凭据通过环境变量传入，不硬编码
- [ ] 不依赖项目内部 Python 对象
- [ ] 区分“能力面”和“源码面”：Skill 可执行 / 可挂载，不代表 Agent 可直接读取 `SKILL.md` 或脚本源码
- [ ] 如有脚本产出给用户，写入 `/mnt/user-data/outputs/`（沙箱可见路径）
- [ ] 如需控制启用状态或 tier，再在 `extensions_config.json` 中声明；未声明时当前实现默认启用，tier 默认为 `foundation`

### 选 Tool + Skill 分层时确认：

- [ ] Tool 负责安全数据入口（tenant 隔离）
- [ ] Skill 负责重计算 / 分析逻辑
- [ ] Tool / Skill 是否对当前 Agent 可见，要以运行时过滤后的结果为准，而不是以“仓库里存在”作为判断
- [ ] Agent SOUL.md 中明确说明两者各自的调用场景

## 相关文档

- [TOOLS_SYSTEM.md](TOOLS_SYSTEM.md) — Tool 系统详解（内置工具、MCP 工具、社区工具）
- [AGENTS_SYSTEM.md](AGENTS_SYSTEM.md) — Agent 多级发现与配置
- [ARCHITECTURE.md](ARCHITECTURE.md) — 系统架构概览
- `skills/public/` — 公共 Skill（通用能力）
- `skills/custom/` — 定制 Skill（工业领域）
- `backend/packages/harness/deerflow/tools/builtins/` — 内置 Tool 实现
- `backend/packages/harness/deerflow/integrations/tools/tool_builder.py` — 集成数据 Tool 工厂
