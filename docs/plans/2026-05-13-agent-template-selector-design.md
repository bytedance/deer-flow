# Agent 子智能体选择器设计文档

## 背景

用户点击左侧菜单中的"AI报告"智能体后，需要展示一个子智能体选择面板，让用户选择具体的报告类型（日报、周报、诊断报告等）。每个"模板"本身就是一个完整的 agent，拥有独立的 SOUL.md、工具集、技能和 prompt 策略。

**核心约束**：

1. 前端代码不耦合业务逻辑
2. 每个"模板"是一个完整的 agent，具备 agent 的所有能力
3. 利用 agent 分组/层级关系来组织，而非在 agent 内部加 templates 字段

## 设计目标

1. 引入 **parent/children 层级关系** — "AI报告"是父 agent，"日报"、"周报"等是子 agent
2. 父 agent 点击后展示子 agent 选择面板
3. 子 agent 是完整的 agent，有自己的 SOUL.md、config.yaml、工具和技能
4. 前端提供通用的层级渲染机制，不感知具体业务

## 架构设计

```text
agents/builtin/
├── ai-report/                    ← 父 agent (parent)
│   ├── config.yaml               ← type: "group", children 自动发现
│   └── SOUL.md
├── ai-report--daily/             ← 子 agent
│   ├── config.yaml               ← parent: "ai-report"
│   └── SOUL.md                   ← 独立的系统提示词
├── ai-report--weekly/            ← 子 agent
│   ├── config.yaml
│   └── SOUL.md
├── ai-report--diagnosis/         ← 子 agent
│   ├── config.yaml
│   └── SOUL.md
└── ...
```

```text
┌─────────────────────────────────────────────────────────┐
│  Backend: Agent 加载                                     │
│  - 扫描所有 agent 目录                                    │
│  - 解析 parent 字段，构建层级关系                          │
│  - API 返回扁平列表，每个 agent 带 type 和 parent 字段    │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│  Frontend (通用组件，不含业务逻辑)                         │
│                                                         │
│  侧边栏: 过滤显示顶层 agent (parent=null)                │
│  设置页面: 显示全部 agent（含子 agent）                    │
│  点击父 agent → 进入子 agent 选择页面                     │
│  点击子 agent → 进入该子 agent 的对话                     │
│                                                         │
│  AgentChildSelector 组件:                                │
│    渲染 children 网格，点击路由到子 agent 对话             │
└─────────────────────────────────────────────────────────┘
```

## 数据模型

### Agent config.yaml — 父 agent

```yaml
# agents/builtin/ai-report/config.yaml
name: ai-report
display_name: "AI报告"
icon: "📋"
description: "擅长自动生成设备状态报告、巡检报告、分析报告"
type: group          # 新增：标识为分组 agent
model: null
tool_groups:
  - bash
```

### Agent config.yaml — 子 agent

```yaml
# agents/builtin/ai-report--daily/config.yaml
name: ai-report--daily
display_name: "日报"
icon: "📋"
description: "每日设备运行概况"
parent: ai-report    # 新增：指向父 agent
model: null
tool_groups:
  - bash
skills:
  - data-analyst
```

```yaml
# agents/builtin/ai-report--weekly/config.yaml
name: ai-report--weekly
display_name: "周报"
icon: "📊"
description: "周度运行趋势与异常统计"
parent: ai-report
model: null
tool_groups:
  - bash
skills:
  - data-analyst
```

```yaml
# agents/builtin/ai-report--diagnosis/config.yaml
name: ai-report--diagnosis
display_name: "诊断报告"
icon: "🔍"
description: "故障诊断分析及结论"
parent: ai-report
model: null
tool_groups:
  - bash
```

```yaml
# agents/builtin/ai-report--failure-analysis/config.yaml
name: ai-report--failure-analysis
display_name: "失效分析报告"
icon: "⚠️"
description: "根因分析与改进建议"
parent: ai-report
model: null
tool_groups:
  - bash
```

```yaml
# agents/builtin/ai-report--monthly/config.yaml
name: ai-report--monthly
display_name: "月度报告"
icon: "📈"
description: "月度综合运行分析"
parent: ai-report
model: null
tool_groups:
  - bash
skills:
  - data-analyst
```

```yaml
# agents/builtin/ai-report--trend/config.yaml
name: ai-report--trend
display_name: "趋势分析报告"
icon: "📉"
description: "长期趋势与预测"
parent: ai-report
model: null
tool_groups:
  - bash
skills:
  - data-analyst
```

```yaml
# agents/builtin/ai-report--closure/config.yaml
name: ai-report--closure
display_name: "闭环报告"
icon: "✅"
description: "缺陷闭环处理总结"
parent: ai-report
model: null
tool_groups:
  - bash
```

```yaml
# agents/builtin/ai-report--custom/config.yaml
name: ai-report--custom
display_name: "自定义模板"
icon: "📝"
description: "按需定制报告格式"
parent: ai-report
model: null
tool_groups:
  - bash
```

### 命名约定

子 agent 目录名使用 `{parent}--{child}` 格式（双横线分隔），这只是**推荐的命名规范**，便于文件系统中直观识别层级关系。系统依赖 config.yaml 中的 `parent` 字段确定层级关系，不通过名称解析。即使 agent 名称本身包含 `--`，也不会产生歧义。

### 前端 TypeScript 类型

```typescript
// core/agents/types.ts — 修改
export interface Agent {
  name: string;
  description: string;
  display_name: string | null;
  icon: string | null;
  model: string | null;
  tool_groups: string[] | null;
  skills: string[] | null;
  mcp_servers: string[] | null;
  tags: string[] | null;
  source: AgentSource;
  editable: boolean;
  enabled: boolean;
  soul?: string | null;
  // 新增层级字段
  type?: "agent" | "group" | null;   // group = 父 agent，新对话时显示子 agent 选择器
  parent?: string | null;             // 子 agent 指向父 agent name
}
```

注意：`Agent` 类型中**不包含** `children` 字段。列表接口返回扁平数组，前端通过 `useMemo` 按 `parent` 字段分组构建树结构。这避免了 TanStack Query 缓存重叠和响应体膨胀的问题。

### 后端 API 变更

**`GET /api/agents`** — 列表接口（向后兼容）：

- **不改变现有行为**：继续返回所有 agent 的扁平列表
- 每个 agent 对象新增 `type` 和 `parent` 字段（可选，默认 null）
- 前端各处按需过滤：侧边栏过滤 `!parent`，设置页面显示全部

**`GET /api/agents/{name}`** — 详情接口：

- 返回 agent 详情，包含 `type` 和 `parent` 字段
- **不返回 `children` 列表** — 前端统一从 `useAgents()` 全量列表中按 `parent` 字段过滤，避免详情接口额外扫描其他 agent，保持后端改动最小化

### 前端数据层 — 树构建

```typescript
// core/agents/hooks.ts — 新增
export function useAgentChildren(parentName: string | null | undefined) {
  const { agents } = useAgents();
  return useMemo(
    () => agents.filter((a) => a.parent === parentName && a.enabled),
    [agents, parentName],
  );
}
```

侧边栏过滤逻辑：

```typescript
// workspace-nav-chat-list.tsx
const enabledAgents = agents.filter((a) => a.enabled && !a.parent);
```

设置页面保持现有逻辑（显示全部 agent），子 agent 缩进展示在父 agent 下方。

## 前端组件设计

### AgentChildSelector（通用组件）

```text
位置: frontend/src/components/workspace/agent-child-selector.tsx
```

**职责**：

- 接收 `children: Agent[]` 和 `onSelect: (agent: Agent) => void`
- 渲染为网格布局（响应式 2-4 列）
- 每个卡片显示 icon + display_name + description
- 点击卡片调用 `onSelect(childAgent)`

**不包含**：

- 不知道自己在哪个 agent 下
- 不知道子 agent 的业务含义
- 不发起网络请求（数据由父组件传入）

### 路由与页面行为

**推荐方案**：复用现有 `/workspace/agents/{name}/chats/new` 路由，在 `AgentChatPage` 中根据 `agent.type` 条件渲染：

```tsx
// AgentChatPage 中
extraHeader={
  isNewThread && agent?.type === "group" ? (
    <>
      <AgentWelcome agent={agent} agentName={agent_name} />
      <AgentChildSelector
        children={childAgents}
        onSelect={(child) => {
          router.push(`/workspace/agents/${child.name}/chats/new`);
        }}
      />
    </>
  ) : isNewThread ? (
    <AgentWelcome agent={agent} agentName={agent_name} />
  ) : null
}
```

其中 `childAgents` 来自 `useAgentChildren(agent_name)` hook。

对于 group 类型的 agent，隐藏输入框（因为新对话需要先选择子 agent）：

```tsx
disabled={agent?.type === "group"}
```

### enabled 级联逻辑

子 agent 的可用性由前端展示层判断，**不修改子 agent 的持久化 `enabled` 状态**：

```typescript
// 判断 agent 是否实际可用
function isAgentAvailable(agent: Agent, allAgents: Agent[]): boolean {
  if (!agent.enabled) return false;
  if (agent.parent) {
    const parent = allAgents.find((a) => a.name === agent.parent);
    if (parent && !parent.enabled) return false;
  }
  return true;
}
```

这样禁用/启用父 agent 是可逆的 — 恢复父 agent 后，子 agent 的 `enabled` 状态不受影响。

## 后端 LangGraph 集成

### 子 agent 注册

每个子 agent 在 LangGraph 中注册为独立的 assistant，与普通 agent 完全一致：

1. 后端启动时扫描 `agents/builtin/` 下所有目录（包括子 agent 目录）
2. 每个包含 `config.yaml` 的目录注册为一个独立的 LangGraph assistant
3. `parent` 字段仅影响 API 层的元数据返回，不影响 LangGraph 的 graph 构建
4. 子 agent 的 `SOUL.md` 作为 system prompt 注入，与普通 agent 行为一致

### 对话创建

前端传递 `context.agent_name = "ai-report--weekly"` 时，后端按标准流程：

1. 根据 `agent_name` 查找对应的 agent config
2. 加载该 agent 的 SOUL.md 作为 system prompt
3. 加载该 agent 配置的 tool_groups 和 skills
4. 创建 thread 并开始对话

**无需特殊处理** — 子 agent 在 LangGraph 层面就是一个普通 agent。

## 与"模板方案"的对比

| 维度 | 模板方案 (templates 字段) | 子 agent 方案 (parent/children) |
| ---- | ---- | ---- |
| 独立 SOUL.md | 共享父 agent 的 prompt | 每个子 agent 独立 |
| 独立工具集 | 共享父 agent 的 tools | 每个子 agent 可配置不同 tools |
| 独立技能 | 共享 | 独立 |
| 独立对话历史 | 同一 agent 下 | 独立 thread |
| 可单独启用/禁用 | 不支持 | 支持 |
| 可被其他系统引用 | 不支持 | 标准 agent name |
| 配置复杂度 | 低（一个文件） | 中（每个子 agent 一个目录） |
| 扩展性 | 低 | 高（子 agent 可以有自己的子 agent） |

## 解耦保证

| 层级 | 职责边界 |
| ---- | ---- |
| config.yaml | 定义 agent 层级关系（`type: group` / `parent: xxx`） |
| Backend | 解析层级关系，API 返回扁平列表 + parent 字段 |
| Agent type | 声明 `type?`, `parent?`（通用数据结构） |
| AgentChildSelector | 纯展示组件，接收 Agent[] 渲染网格 |
| AgentChatPage | 条件渲染：type=group 显示选择器，否则正常对话 |
| 侧边栏 | 过滤：只显示 parent=null 的顶层 agent |

**前端代码中不会出现**：

- "日报"、"周报"等业务文案
- 报告类型的判断逻辑
- 特定 agent 的 if/else 分支
- 任何 `ai-report` 相关的硬编码

## 目录结构（最终状态）

```text
agents/builtin/
├── fault-diagnosis/          ← 独立 agent（无子 agent）
├── anomaly-judgment/         ← 独立 agent
├── monitoring-analysis/      ← 独立 agent
├── defect-closure/           ← 独立 agent
├── ai-report/                ← 父 agent (type: group)
│   ├── config.yaml
│   └── SOUL.md
├── ai-report--daily/         ← 子 agent (parent: ai-report)
│   ├── config.yaml
│   └── SOUL.md
├── ai-report--weekly/
│   ├── config.yaml
│   └── SOUL.md
├── ai-report--diagnosis/
│   ├── config.yaml
│   └── SOUL.md
├── ai-report--failure-analysis/
│   ├── config.yaml
│   └── SOUL.md
├── ai-report--monthly/
│   ├── config.yaml
│   └── SOUL.md
├── ai-report--trend/
│   ├── config.yaml
│   └── SOUL.md
├── ai-report--closure/
│   ├── config.yaml
│   └── SOUL.md
└── ai-report--custom/
    ├── config.yaml
    └── SOUL.md
```

## 实施步骤

### Phase 1: 后端 — 层级关系支持

1. config.yaml schema 新增 `type` 和 `parent` 字段（AgentConfig dataclass 添加两个可选字段）
2. Agent 加载逻辑：解析新字段，序列化到 API 响应中（AgentResponse 新增 `type` 和 `parent`）
3. `GET /api/agents` 保持返回扁平全量列表（向后兼容），每个 agent 带 `type` 和 `parent`
4. 子 agent 在 LangGraph 中无需特殊处理（与普通 agent 一致，按 agent_name 动态加载）

### Phase 2: 前端 — 类型 + 通用组件

1. `Agent` type 新增 `type?`, `parent?` 字段
2. 新增 `useAgentChildren(parentName)` hook
3. 侧边栏过滤：只显示 `!agent.parent` 的 agent
4. 新建 `AgentChildSelector` 组件（纯 UI，~80 行）
5. `AgentChatPage` 中根据 `agent.type === "group"` 条件渲染选择器
6. group 类型新对话时隐藏输入框

### Phase 3: 配置 — 创建子 agent

1. 创建 8 个子 agent 目录（ai-report--daily 等）
2. 每个子 agent 编写独立的 SOUL.md（针对性的系统提示词）
3. 配置各自的 tool_groups 和 skills

## 验证

1. `pnpm typecheck` 通过
2. `GET /api/agents` 返回全量列表（含子 agent），向后兼容
3. 侧边栏只显示 5 个顶层 agent（不显示子 agent）
4. 点击"AI报告" → 显示子 agent 选择网格（8 个卡片）
5. 点击"周报"卡片 → 路由到 ai-report--weekly 的对话页面
6. ai-report--weekly 有独立的 SOUL.md 和对话能力
7. 禁用"AI报告"父 agent → 侧边栏不显示，子 agent 不可用（但子 agent 自身 enabled 状态不变）
8. 重新启用"AI报告" → 子 agent 恢复可用
9. 其他无子 agent 的智能体（故障诊断等）行为不变
