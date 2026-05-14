# 日报 UX 改进：设备选择 + 自动启动

> 日期：2026-05-14
> 状态：Draft
> 关联 Agent：`ai-report--daily`

## 背景

当前日报 Agent 存在两个用户体验问题：

1. **设备选择不直观**：Round 1 表单中 `scope_filter` 是纯文本框，用户需要手动输入"A区,B区"或"SE-001,SE-002"，容易出错且不直观。
2. **需要额外发消息才能开始**：用户点击"日报"Agent 后看到欢迎页，必须手动输入"生成日报"，Agent 才会渲染参数表单，多了一步无意义的对话。

## 需求 1：方便选择到具体设备

### 现状

```
Round 1 表单：
  - 日报日期（date）
  - 设备类型（select）
  - 设备范围（select: 全部/按区域/指定设备）
  - 区域名称或设备ID（text，手动输入）  ← 问题所在
  - 对比基准（select）

Round 2 表单：
  - KPI 多选（checkbox）
```

`scope_filter` 文本框的问题：
- 用户不知道有哪些区域可选
- 需要手动输入设备 ID，容易拼写错误
- 无法看到每个区域包含多少台设备
- **无法浏览和选择具体设备**（核心需求）

### 挑战

单个设备类型可有 1000+ 台设备。不能用 checkbox 逐个列出，也不能用简单 select 下拉——需要**可搜索、可多选、按区域分组**的设备选择器。当前 GenUI form 组件不支持此类复杂控件。

### 方案：新增 `multi-select` 表单字段类型

在 GenUI form 组件中新增 `multi-select` 类型，支持：
- 可搜索（输入关键词过滤选项）
- 可多选（checkbox 形式批量勾选）
- 分组（按 `group` 字段将选项分区域展示）
- 全选/全不选（按组或全局）
- 选中计数显示

#### 前端新字段类型定义

```typescript
// FormBlock.tsx 中的 FormField 扩展
interface FormField {
  // ... 现有字段 ...
  type: "text" | "number" | "email" | ... | "multi-select";  // 新增
  options?: {
    label: string;
    value: string;
    group?: string;        // 分组标签，如 "A区"
    description?: string;  // 描述信息，如 "换热器-001"
  }[];
  searchable?: boolean;    // 是否启用搜索过滤
  max_visible?: number;    // 折叠显示的最大高度（条目数），超出可滚动
}
```

#### react-hook-form 集成约束

当前 FormBlock 所有字段均使用 `register()` 绑定原生 HTML 元素。multi-select 是自定义 React 组件（搜索框 + checkbox 列表），不是原生 DOM 元素，`register()` 无法驱动它。必须使用 react-hook-form 的 `Controller` 组件：

```typescript
import { useForm, Controller } from "react-hook-form";

// useForm 解构增加 control
const { register, control, handleSubmit, formState: { errors } } = useForm({
  defaultValues: default_values as Record<string, unknown>,  // 放宽类型，支持 string[]
});

// multi-select 分支使用 Controller 而非 register
} else if (field.type === "multi-select") {
  return (
    <Controller
      name={field.name}
      control={control}
      rules={buildValidationRules(field)}
      render={({ field: controllerField }) => (
        <MultiSelectField
          value={controllerField.value as string[]}
          onChange={controllerField.onChange}
          options={field.options ?? []}
          disabled={isDisabled}
          searchable={field.searchable}
          maxVisible={field.max_visible}
        />
      )}
    />
  );
}
```

> **注意**：`defaultValues` 的类型需从 `Record<string, string>` 放宽为 `Record<string, unknown>`，否则 TypeScript 不接受 `string[]` 类型的默认值。此改动对现有字段无影响（`string` 是 `unknown` 的子类型）。

#### 交互设计

```
┌─────────────────────────────────────────────┐
│ 选择设备                                      │
│ ┌─────────────────────────────────────────┐  │
│ │ 🔍 搜索设备ID或名称...                    │  │
│ └─────────────────────────────────────────┘  │
│                                               │
│ ☑ 全选 (1000 台)                              │
│                                               │
│ ▼ A区 (250 台)          [全选] [全不选]        │
│   ☑ SE-001  换热器-001                        │
│   ☑ SE-002  冷却器-002                        │
│   ☑ SE-003  塔器-003                          │
│   ☑ SE-004  容器-004                          │
│   ... (滚动查看更多)                           │
│                                               │
│ ▼ B区 (250 台)          [全选] [全不选]        │
│   ☑ SE-251  换热器-251                        │
│   ☑ SE-252  冷却器-252                        │
│   ...                                         │
│                                               │
│ 已选：1000 / 1000 台                          │
└─────────────────────────────────────────────┘
```

#### 表单流程改造

将 Round 1 拆为 Round 1 → Round 1.5：

| 轮次 | callback_id | 内容 | 改动 |
|------|-------------|------|------|
| Round 1 | `daily-report-scope` | 日期、设备类型、对比基准 | 移除 `equipment_scope` 和 `scope_filter` |
| Round 1.5（新增） | `daily-report-equipment` | 设备多选（multi-select），按区域分组 | **新增** |
| Round 2 | `daily-report-confirm` | KPI 多选（不变） | 不变 |

**Round 1 表单（简化）**：

```json
{
  "component": "form",
  "callback_id": "daily-report-scope",
  "props": {
    "title": "生成设备运行日报",
    "fields": [
      {"name": "report_date", "label": "日报日期", "type": "date", "required": true},
      {
        "name": "equipment_type", "label": "设备类型", "type": "select", "required": true,
        "options": [
          {"label": "全部", "value": "all"},
          {"label": "静设备", "value": "static_equipment"},
          {"label": "旋转机组", "value": "rotating_machinery"},
          {"label": "机泵", "value": "pump"},
          {"label": "往复机组", "value": "reciprocating_machinery"}
        ]
      },
      {
        "name": "compare_with", "label": "对比基准", "type": "select", "required": true,
        "options": [
          {"label": "前一日", "value": "previous_day"},
          {"label": "上周同日", "value": "previous_week"},
          {"label": "不对比", "value": "none"}
        ]
      }
    ],
    "default_values": {"equipment_type": "all", "compare_with": "previous_day"},
    "submit_label": "下一步"
  }
}
```

**Round 1 回调 → 查设备列表 → 渲染 Round 1.5**：

Agent 调用 `list_equipment.py --type "{type}" --scope all --limit 10000` 获取完整设备列表，然后生成 multi-select 表单：

```json
{
  "component": "form",
  "callback_id": "daily-report-equipment",
  "props": {
    "title": "选择设备",
    "description": "已匹配：静设备 · 1000 台。取消勾选不需要的设备。",
    "fields": [
      {
        "name": "equipment_ids",
        "label": "设备列表",
        "type": "multi-select",
        "searchable": true,
        "max_visible": 10,
        "options": [
          {"label": "SE-001", "value": "SE-001", "group": "A区", "description": "换热器-001"},
          {"label": "SE-002", "value": "SE-002", "group": "A区", "description": "冷却器-002"}
        ]
      }
    ],
    "default_values": {
      "equipment_ids": ["SE-001", "SE-002", "...全部设备ID"]
    },
    "submit_label": "下一步"
  }
}
```

**Round 1.5 回调 → 解析选中设备**：

- `payload.equipment_ids` 为用户选中的设备 ID 数组
- 设备数量 ≤ 10：走 `--equipment` 指定模式
- 设备数量 > 10 且等于某区域全量：走 `--scope area --scope-filter "A区,B区"` 聚合模式
- 设备数量 > 10 且为跨区域混选：走 `--equipment` 但启用聚合模式

#### list_equipment.py 返回值增强

```python
# 现有返回已包含 equipment 列表，需要提高 limit 并确保包含 area 字段：
{
  "equipment": [
    {"id": "SE-001", "name": "换热器-001", "area": "A区", "sub_type": "换热器"},
    ...
  ],
  "areas": ["A区", "B区", "C区", "D区"],
  "area_counts": {"A区": 250, "B区": 250, "C区": 250, "D区": 250},  // 新增
  "total_matched": 1000,
  ...
}
```

#### Payload 体积约束

`multi-select` 默认全选时，`default_values.equipment_ids` 和提交后的 `payload.equipment_ids` 均为完整 ID 数组。用户提交后 payload 经 `genui:interaction-submitted` → `sendMessage()` 序列化为 hidden HumanMessage 发给 LangGraph，全程 JSON 序列化。

- 1000 台设备（~15KB）：无问题
- 5000+ 台设备：需要考虑分页加载或"全选时不传 ID 列表、仅传标记"的压缩策略

当前 demo 数据单类型最大 1000 台，实际生产环境需根据数据规模评估。

### 需要改动的文件

| 文件 | 改动 | 代码量 |
|------|------|--------|
| `frontend/src/components/genui/FormBlock.tsx` | 新增 `multi-select` 字段渲染（搜索框 + 分组 + checkbox + 全选 + 滚动） | ~150 行 |
| `frontend/src/core/genui/validator.ts` | `formFieldSchema` 的 type 枚举增加 `"multi-select"`；options schema 扩展 `group`、`description` 可选字段；新增 `searchable`、`max_visible` 可选字段 | ~15 行 |
| `skills/custom/data-analyst/scripts/list_equipment.py` | 返回值增加 `area_counts` 字段 | ~10 行 |
| `agents/builtin/ai-report--daily/SOUL.md` | 重构表单流程，Round 1 简化 + 新增 Round 1.5 设备选择 | SOUL.md |

> **注意**：`validator.ts` 中的 Zod schema 是**阻塞性依赖**——`GenUIRenderer` 在渲染前会用 Zod 校验 form props，如果 `type: "multi-select"` 不在枚举中，整个 form block 会被静默拒绝、不渲染。必须同步修改。

### 优势

- 用户可以看到**每一台设备**的 ID、名称、所属区域
- 支持搜索过滤，快速定位目标设备
- 按区域分组 + 全选/全不选，批量操作高效
- 默认全选，用户可取消不需要的设备
- `multi-select` 是 GenUI 通用组件，其他 Agent 也可以复用

---

## 需求 2：点击日报直接开始

### 现状

```
用户点击"日报" Agent
  → 看到 AgentWelcome（图标 + 名称 + 描述）
  → 需要手动输入"生成日报"
  → Agent 才渲染参数表单
```

这一步"输入消息触发表单"是冗余的，因为日报 Agent 的唯一功能就是生成日报。

### 方案：为 AgentConfig 增加 `starters` 字段 + 前端自动触发

#### 2a. 后端：AgentConfig 增加 `starters`

```python
# agents_config.py

class StarterConfig(BaseModel):
    label: str
    prompt: str
    icon: str | None = None
    auto_start: bool = False  # 新线程自动发送

class AgentConfig(BaseModel):
    # ... 现有字段 ...
    starters: list[StarterConfig] | None = None
```

日报 Agent 配置：

```yaml
# agents/builtin/ai-report--daily/config.yaml
name: ai-report--daily
display_name: "日报"
description: "每日设备运行概况"
icon: "📋"
parent: ai-report
order: 1
starters:
  - label: "生成设备运行日报"
    prompt: "生成日报"
    auto_start: true
```

#### 2b. 后端 API：AgentInfo 透传 starters

```python
# agents_config.py

class AgentInfo(BaseModel):
    # ... 现有字段 ...
    starters: list[StarterConfig] | None = None

def to_agent_info(config: AgentConfig, ...) -> AgentInfo:
    return AgentInfo(
        # ... 现有字段 ...
        starters=config.starters,
    )
```

`GET /api/agents` 返回中自然包含 `starters`，无需改路由。

#### 2c. 前端：AgentWelcome 渲染 starter 按钮

```tsx
// agent-welcome.tsx
export function AgentWelcome({ agent, agentName, onStarterClick }: {
  agent: Agent | null | undefined;
  agentName: string;
  onStarterClick?: (prompt: string) => void;
}) {
  return (
    <div>
      {/* 现有图标 + 名称 + 描述 */}
      {agent?.starters && (
        <Suggestions>
          {agent.starters.map((s) => (
            <Suggestion
              key={s.label}
              suggestion={s.label}
              onClick={() => onStarterClick?.(s.prompt)}
            />
          ))}
        </Suggestions>
      )}
    </div>
  );
}
```

#### 2d. 前端：新线程自动发送

```tsx
// Agent chat page.tsx
useEffect(() => {
  if (!isNewThread || !agent?.starters) return;
  const autoStarter = agent.starters.find((s) => s.auto_start);
  if (autoStarter) {
    handleSubmit({ text: autoStarter.prompt, files: [] });
  }
}, [isNewThread, agent]);
```

`auto_start` 触发的消息可通过 `additionalKwargs: { hide_from_ui: true }` 隐藏，用户不会看到"生成日报"这条消息。

### 需要改动的文件

| 文件 | 改动 | 代码量 |
|------|------|--------|
| `backend/packages/harness/deerflow/config/agents_config.py` | 增加 `StarterConfig`、`AgentConfig.starters`、`AgentInfo.starters` | ~15 行 |
| `backend/app/gateway/routers/agents.py` | `AgentResponse` 模型增加 `starters` 字段；`_agent_config_to_response()` 映射 `starters` | ~10 行 |
| `agents/builtin/ai-report--daily/config.yaml` | 增加 `starters` 配置 | ~4 行 |
| `frontend/src/core/agents/types.ts` | `Agent` 类型增加 `starters` 字段 | ~5 行 |
| `frontend/src/components/workspace/agent-welcome.tsx` | 渲染 starter 按钮 | ~15 行 |
| `frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx` | `auto_start` 自动发送逻辑 | ~10 行 |

> **注意**：数据流经过三层模型 `AgentConfig → AgentResponse → HTTP JSON → Frontend Agent`。`AgentResponse` 是独立的 Pydantic 响应模型（定义在 `agents.py`），如果不在此模型中声明 `starters`，Pydantic 序列化时会静默丢弃该字段，前端永远收不到。同样，`load_agent_config()` 中的白名单过滤 `known_fields = set(AgentConfig.model_fields.keys())` 会丢弃 config.yaml 中未在 `AgentConfig` 声明的字段。两处都必须同步修改。

### 用户体验（改进后）

```
用户点击"日报" Agent
  → 自动创建线程并发送隐藏消息
  → Agent 立即渲染参数表单
  → 用户直接填写日期、勾选区域、选 KPI
  → 生成日报
```

全程零冗余对话。

### 通用性

`starters` 是 AgentConfig 层面的通用能力，所有 Agent 都可以配置：

```yaml
# 其他 Agent 示例
starters:
  - label: "新建周报"
    prompt: "生成周报"
    auto_start: true
  - label: "查看历史报告"
    prompt: "列出最近的报告"
```

---

## 实施建议

| 优先级 | 需求 | 风险 | 工作量 |
|--------|------|------|--------|
| P0 | 需求 1（设备选择） | 中（前端新增 multi-select 组件 + Zod schema） | 1.5 天 |
| P0 | 需求 2（自动启动） | 中（前后端三层模型联动） | 1 天 |

两者互不依赖，可以并行。需求 2 涉及的改动层数更多（AgentConfig → AgentResponse → 前端类型 → 两个组件），但单点代码量小；需求 1 的前端组件工作量更大（multi-select 含搜索/分组/全选/虚拟滚动）。
