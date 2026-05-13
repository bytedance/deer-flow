# Sprint Plan: Agent 子智能体选择器实施

## Sprint Summary

```
Sprint Goal: 实现 agent 层级关系，用户点击"AI报告"后可选择子智能体开始对话
Duration: 1 week (2026-05-14 ~ 2026-05-20)
Team Capacity: 20 story points (假设 1 全栈开发 + 15% buffer)
Committed Stories: 20 story points across 10 stories
Buffer: 0 story points (紧凑 sprint，如需 buffer 可延长至 6 天)

Stories:
1. [后端] AgentConfig 新增 type/parent 字段 — 2pt — 后端 — 无依赖
2. [后端] AgentResponse 序列化 type/parent — 2pt — 后端 — 依赖 #1
3. [前端] Agent TypeScript 类型新增字段 — 1pt — 前端 — 依赖 #2
4. [前端] useAgentChildren hook + isAgentAvailable 工具函数 — 2pt — 前端 — 依赖 #3
5. [前端] 侧边栏过滤子 agent — 1pt — 前端 — 依赖 #4
6. [前端] AgentChildSelector 通用组件 — 3pt — 前端 — 依赖 #4
7. [前端] AgentChatPage 条件渲染集成 — 3pt — 前端 — 依赖 #6
8. [前端] 设置页面子 agent 层级展示 — 2pt — 前端 — 依赖 #4
9. [配置] 创建 8 个子 agent 目录和 SOUL.md — 4pt — 全栈 — 依赖 #1
10. [验证] 端到端验证 + enabled 级联测试 — 0pt — 全栈 — 依赖 #7, #8, #9

Risks:
- API 字段新增可能影响现有前端消费方 → 字段可选且默认 null，向后兼容
- 子 agent SOUL.md 质量影响用户体验 → 先写骨架，后续迭代优化
- 侧边栏过滤可能导致已有 agent 对话页面的路由匹配异常 → 保留所有路由，仅过滤显示
```

---

## Stories 详细拆分

### Story 1: [后端] AgentConfig 新增 type/parent 字段

**估点**: 2 SP  
**优先级**: P0 (阻塞所有后续工作)  
**负责**: 后端

**验收标准**:

- [ ] `AgentConfig` dataclass 新增 `type: str | None = None` 和 `parent: str | None = None`
- [ ] `yaml.safe_load()` 能正确解析含 `type`/`parent` 的 config.yaml
- [ ] 不含这些字段的现有 config.yaml 加载正常（默认 None）
- [ ] 单元测试覆盖新字段解析

**实施要点**:

- 文件: `backend/packages/harness/deerflow/config/agents_config.py`
- 在 `AgentConfig` dataclass 中添加两个可选字段
- `type` 取值: `None`（默认，等同 "agent"）或 `"group"`
- `parent` 取值: `None`（顶层 agent）或父 agent 的 name

---

### Story 2: [后端] AgentResponse 序列化 type/parent

**估点**: 2 SP  
**优先级**: P0  
**负责**: 后端  
**依赖**: Story #1

**验收标准**:

- [ ] `AgentResponse` Pydantic model 新增 `type` 和 `parent` 字段
- [ ] `GET /api/agents` 返回的每个 agent 包含 `type` 和 `parent`（默认 null）
- [ ] `GET /api/agents/{name}` 同样返回这两个字段
- [ ] 现有 API 消费方不受影响（字段可选，默认 null）

**实施要点**:

- 文件: `backend/app/gateway/routers/agents.py`
- `AgentResponse` 新增: `type: str | None = None`, `parent: str | None = None`
- 从 `AgentConfig` 映射到 `AgentResponse` 时传递这两个字段

---

### Story 3: [前端] Agent TypeScript 类型新增字段

**估点**: 1 SP  
**优先级**: P0  
**负责**: 前端  
**依赖**: Story #2 (API 已部署)

**验收标准**:

- [ ] `Agent` interface 新增 `type?: "agent" | "group" | null` 和 `parent?: string | null`
- [ ] `pnpm typecheck` 通过
- [ ] 现有使用 `Agent` 类型的代码无需修改

**实施要点**:

- 文件: `frontend/src/core/agents/types.ts`
- 添加两个可选字段，不影响现有代码

---

### Story 4: [前端] useAgentChildren hook + isAgentAvailable 工具函数

**估点**: 2 SP  
**优先级**: P1  
**负责**: 前端  
**依赖**: Story #3

**验收标准**:

- [ ] `useAgentChildren(parentName)` 从全量 agent 列表中过滤出指定父 agent 的已启用子 agent
- [ ] `isAgentAvailable(agent, allAgents)` 判断 agent 是否实际可用（含父 agent enabled 级联）
- [ ] 返回值随 agents 列表变化自动更新
- [ ] parentName 为 null/undefined 时返回空数组
- [ ] 父 agent 禁用时，其子 agent 通过 isAgentAvailable 判定为不可用

**实施要点**:

- 文件: `frontend/src/core/agents/hooks.ts`
- 使用 `useMemo` 从 `useAgents()` 结果中过滤
- 新增工具函数 `isAgentAvailable`，供侧边栏和设置页面复用

```typescript
export function useAgentChildren(parentName: string | null | undefined) {
  const { agents } = useAgents();
  return useMemo(
    () => agents.filter((a) => a.parent === parentName && a.enabled),
    [agents, parentName],
  );
}

export function isAgentAvailable(agent: Agent, allAgents: Agent[]): boolean {
  if (!agent.enabled) return false;
  if (agent.parent) {
    const parent = allAgents.find((a) => a.name === agent.parent);
    if (parent && !parent.enabled) return false;
  }
  return true;
}
```

---

### Story 5: [前端] 侧边栏过滤子 agent

**估点**: 1 SP  
**优先级**: P1  
**负责**: 前端  
**依赖**: Story #4

**验收标准**:

- [ ] 侧边栏智能体列表只显示 `parent` 为 null/undefined 的顶层 agent
- [ ] 子 agent 不出现在侧边栏
- [ ] 现有无 parent 的 agent 显示不受影响

**实施要点**:

- 文件: `frontend/src/components/workspace/workspace-nav-chat-list.tsx`
- 修改过滤条件: `agents.filter((a) => a.enabled && !a.parent)`

---

### Story 6: [前端] AgentChildSelector 通用组件

**估点**: 3 SP  
**优先级**: P1  
**负责**: 前端  
**依赖**: Story #4

**验收标准**:

- [ ] 组件接收 `children: Agent[]` 和 `onSelect: (agent: Agent) => void`
- [ ] 渲染为响应式网格（sm: 2列, md: 3列, lg: 4列）
- [ ] 每个卡片显示 icon + display_name + description
- [ ] 点击卡片触发 onSelect
- [ ] 空列表时不渲染
- [ ] 组件不包含任何业务逻辑或硬编码文案

**实施要点**:

- 新建文件: `frontend/src/components/workspace/agent-child-selector.tsx`
- 使用项目已有的 Card 或自定义卡片样式
- 纯展示组件，约 80 行代码

---

### Story 7: [前端] AgentChatPage 条件渲染集成

**估点**: 3 SP  
**优先级**: P1  
**负责**: 前端  
**依赖**: Story #6

**验收标准**:

- [ ] `agent.type === "group"` 时，新对话页面显示 AgentWelcome + AgentChildSelector
- [ ] group 类型时输入框禁用（不可直接对话）
- [ ] 点击子 agent 卡片路由到 `/workspace/agents/{child.name}/chats/new`
- [ ] 非 group 类型的 agent 行为不变
- [ ] `pnpm typecheck` 通过

**实施要点**:

- 文件: `frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx`
- 在 `extraHeader` 中条件渲染
- 使用 `useAgentChildren(agent_name)` 获取子 agent 列表

---

### Story 8: [前端] 设置页面子 agent 层级展示

**估点**: 2 SP  
**优先级**: P1  
**负责**: 前端  
**依赖**: Story #4

**验收标准**:

- [ ] 设置页面智能体标签页中，子 agent 缩进展示在父 agent 下方
- [ ] 父 agent 禁用时，其下方子 agent 的 Switch 显示为 disabled 状态
- [ ] 子 agent 单独启用/禁用不影响父 agent 状态
- [ ] 使用 `isAgentAvailable` 判断实际可用性

**实施要点**:

- 文件: `frontend/src/components/workspace/settings/agent-settings-page.tsx`
- 在 `useGroupedAgents()` 分组后，对每个 group 内的 agent 按 parent 关系排序
- 子 agent 渲染时增加左侧缩进（`ml-6`）
- 父 agent 禁用时子 agent 的 Switch 添加 `disabled` 属性

---

### Story 9: [配置] 创建 8 个子 agent 目录和 SOUL.md

**估点**: 4 SP  
**优先级**: P2  
**负责**: 全栈  
**依赖**: Story #1

**验收标准**:

- [ ] 创建 8 个子 agent 目录: ai-report--daily, ai-report--weekly, ai-report--diagnosis, ai-report--failure-analysis, ai-report--monthly, ai-report--trend, ai-report--closure, ai-report--custom
- [ ] 每个目录包含 config.yaml（含 parent: ai-report）和 SOUL.md
- [ ] 父 agent ai-report 的 config.yaml 新增 `type: group`
- [ ] 每个子 agent 的 SOUL.md 包含针对性的系统提示词
- [ ] 各子 agent 配置合理的 tool_groups 和 skills
- [ ] 后端能正确扫描和加载所有子 agent

**实施要点**:

- 目录: `agents/builtin/ai-report--*/`
- 每个 SOUL.md 需要针对报告类型编写专业的系统提示词
- 需要数据分析能力的子 agent 配置 `skills: [data-analyst]`

---

### Story 10: [验证] 端到端验证 + enabled 级联测试

**估点**: 0 SP (验证任务，不计入开发点数)  
**优先级**: P0  
**负责**: 全栈  
**依赖**: Story #7, #8, #9

**验收标准**:

- [ ] 侧边栏只显示 5 个顶层 agent（不显示子 agent）
- [ ] 点击"AI报告" → 显示子 agent 选择网格（8 个卡片）
- [ ] 点击"周报"卡片 → 路由到 ai-report--weekly 的对话页面并正常对话
- [ ] 设置页面：子 agent 缩进展示在父 agent 下方
- [ ] 禁用"AI报告"父 agent → 侧边栏不显示，设置页面子 agent Switch 禁用
- [ ] 重新启用"AI报告" → 子 agent 恢复可用，enabled 状态不变
- [ ] 其他无子 agent 的智能体行为不变
- [ ] `pnpm typecheck` + `pnpm lint` 通过

---

## 依赖关系图

```text
Story #1 (后端 config)
  ├── Story #2 (后端 API) → Story #3 (前端类型)
  │                              ├── Story #4 (hook + isAgentAvailable)
  │                              │     ├── Story #5 (侧边栏)
  │                              │     ├── Story #6 (组件) → Story #7 (集成)
  │                              │     └── Story #8 (设置页面)
  │                              └─────────────────────────────────────── Story #10 (验证)
  └── Story #9 (配置文件) ──────────────────────────────────────────────┘
```

**关键路径**: #1 → #2 → #3 → #4 → #6 → #7 → #10

---

## 每日计划

| 日期 | 计划 |
| ---- | ---- |
| Day 1 (周三) | Story #1 + #2: 后端 AgentConfig + AgentResponse 改动 |
| Day 2 (周四) | Story #3 + #4 + #5: 前端类型、hook（含 isAgentAvailable）、侧边栏过滤 |
| Day 3 (周五) | Story #6 + #8: AgentChildSelector 组件 + 设置页面层级展示 |
| Day 4 (周一) | Story #7: AgentChatPage 集成 + Story #9 开始 |
| Day 5 (周二) | Story #9 完成: 子 agent SOUL.md 编写 + Story #10 端到端验证 |

---

## 风险与缓解

| 风险 | 影响 | 概率 | 缓解措施 |
| ---- | ---- | ---- | ---- |
| API 新增字段导致旧版前端报错 | 中 | 低 | 字段可选且默认 null，JSON 序列化时 null 字段可省略 |
| 子 agent SOUL.md 质量不足 | 低 | 中 | 先写骨架版本保证功能可用，后续 sprint 迭代优化 |
| 侧边栏过滤影响已有 agent 路由 | 高 | 低 | 仅过滤显示，不改变路由结构，所有 URL 仍可直接访问 |
| AgentChildSelector 样式与设计稿不一致 | 低 | 中 | 先实现功能，样式微调放入 buffer |
| useAgents() 返回大量子 agent 影响性能 | 低 | 低 | 当前 agent 总数 < 20，无性能问题；未来可加分页 |
| enabled 级联逻辑遗漏边界情况 | 中 | 低 | Story #10 专项验证级联场景 |

---

## Definition of Done

- [ ] 所有 Story 验收标准通过
- [ ] `pnpm typecheck` 通过
- [ ] `pnpm lint` 无新增 error
- [ ] 后端 API 测试通过
- [ ] 端到端验证：侧边栏 → 点击 AI报告 → 选择子 agent → 进入对话
- [ ] enabled 级联验证：禁用/启用父 agent 后子 agent 行为正确
- [ ] 设置页面：子 agent 层级展示正确
- [ ] 非 group agent 行为无回归
