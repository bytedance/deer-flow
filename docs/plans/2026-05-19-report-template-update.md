# 报告模板/报告历史菜单动态化设计

## Context

当前侧边栏 [workspace-nav-chat-list.tsx](frontend/src/components/workspace/workspace-nav-chat-list.tsx#L131-L159) 中，"报告模板" 和 "报告历史" 是**硬编码静态菜单项**。它们始终可见，不跟随任何开关控制，与系统中 agent 动态加载的模式不一致（agents 通过 `useAgents()` 加载 → filter by `enabled` → sort by `order` → 动态渲染）。

用户希望这两个菜单项跟随 `ai-report--custom` 自定义模板 agent：
- agent 启用 → 菜单出现
- agent 禁用 → 菜单消失
- 排序可通过 agent 配置调整

## 数据流分析

当前 agent 数据从配置文件到前端渲染的完整链路：

```
agents/builtin/ai-report--custom/config.yaml
  → load_agent_config() / scan_builtin_agents()
  → AgentConfig (Pydantic, line 188 过滤 unknown fields)
  → _agent_config_to_response() → AgentResponse (API model)
  → GET /api/agents → JSON
  → useAgents() → Agent (TypeScript type)
  → WorkspaceNavChatList 渲染
```

**关键发现**：`agents_config.py:188-189` 会**静默丢弃** `AgentConfig.model_fields` 中未定义的字段，因此 `nav_items` 必须依次添加到 `AgentConfig`、`AgentResponse`（或通过 `_agent_config_to_response` 映射）和前端 `Agent` 类型。

## 方案

### 核心思路：Agent config 扩展 `nav_items` 字段

在 agent 配置体系中新增 `nav_items`，声明该 agent 希望在侧边栏展示的导航入口。当 agent 被禁用时，其 nav_items 自动隐藏。

### 改动范围

#### 1. Backend — `deerflow/config/agents_config.py`

新增 `NavItem` 模型，`AgentConfig` 增加 `nav_items` 字段：

```python
class NavItem(BaseModel):
    path: str       # e.g. "/workspace/report-templates"
    label: str      # e.g. "报告模板"
    icon: str       # lucide icon name, e.g. "FileText"

class AgentConfig(BaseModel):
    # ... existing fields ...
    nav_items: list[NavItem] | None = None
```

#### 2. Backend — `app/gateway/routers/agents.py`

`AgentResponse` 新增 `nav_items` 字段，`_agent_config_to_response()` 传递该字段。

#### 3. Frontend — `core/agents/types.ts`

```typescript
export interface NavItem {
  path: string;
  label: string;
  icon: string;
}

// Agent interface 新增:
nav_items?: NavItem[] | null;
```

#### 4. Config — `agents/builtin/ai-report--custom/config.yaml`

```yaml
nav_items:
  - path: /workspace/report-templates
    label: "报告模板"
    icon: FileText
  - path: /workspace/report-runs
    label: "报告历史"
    icon: History
```

#### 5. Frontend — `components/workspace/workspace-nav-chat-list.tsx`

- 删除硬编码的 L131-L159 静态菜单项
- 从 `enabledAgents` 中提取所有 `nav_items`
- 按 agent order + nav_item 数组位置排序
- 在 Agents collapsible 之后渲染动态 nav items

```
Sidebar Menu 结构（变更后）:
├─ 会话列表      (静态)
├─ Agents         (collapsible, 动态)
│  ├─ AI 报告     (group)
│  │  ├─ 日报
│  │  ├─ 周报
│  │  └─ 自定义模板
│  └─ ...
├─ [报告模板]     ← 来自 ai-report--custom.nav_items，仅 agent enabled 时可见
├─ [报告历史]     ← 同上
├─ 知识库管理     (静态)
└─ A2UI 调试     (静态)
```

## 文件改动清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `backend/packages/harness/deerflow/config/agents_config.py` | 编辑 | 新增 NavItem 模型，AgentConfig 加 nav_items |
| `backend/app/gateway/routers/agents.py` | 编辑 | AgentResponse 加 nav_items，传递字段 |
| `frontend/src/core/agents/types.ts` | 编辑 | 新增 NavItem 接口，Agent 加 nav_items |
| `agents/builtin/ai-report--custom/config.yaml` | 编辑 | 添加 nav_items 配置 |
| `frontend/src/components/workspace/workspace-nav-chat-list.tsx` | 编辑 | 删除硬编码菜单项，改为动态提取渲染 |

## 验证方式

1. `make test` — 后端测试全通过
2. `pnpm typecheck` — 前端类型检查通过
3. `pnpm dev` — 侧边栏正常显示"报告模板"和"报告历史"
4. 在设置中禁用 `ai-report--custom` agent → 两个菜单项消失
5. 重新启用 → 菜单项重新出现
6. 其他 agent 的子 agent 列表和行为不受影响
