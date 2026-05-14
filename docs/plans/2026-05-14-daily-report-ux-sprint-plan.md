# 日报 UX 改进 Sprint 实施计划

> **来源设计文档**：[日报 UX 改进设计文档](./2026-05-14-daily-report-ux-improvements.md)
> **前置交付**：[AI 日报 MVP Sprint](./2026-05-13-ai-report-daily-sprint-plan.md)（已完成）、[AI 日报交互优化 Sprint](./2026-05-13-ai-report-daily-ux-improvement-sprint-plan.md)（已完成）
> **范围**：GenUI multi-select 组件开发 + Agent starters/auto_start 通用能力 + 日报 Agent 集成

---

## 1. Sprint Goal

让日报用户在不输入任何文字的情况下直接进入参数表单、可视化浏览和选择每一台具体设备，消除当前日报 Agent 的两个交互痛点。

## 2. Sprint 假设

| 项 | 假设 |
|----|------|
| Sprint 周期 | 1 周（5 工作日） |
| 团队配置 | 1 名全栈/Agent 工程师 |
| 可用容量 | 5 人天 |
| 缓冲 | 20%（约 1 人天） |
| 可承诺容量 | 4 人天 / 16 SP |
| Must 承诺范围 | Stories 1–6（共 16 SP）：multi-select 组件、starters 后端 + 前端、日报集成 |
| Should / Stretch 范围 | Story 7 虚拟滚动优化（2 SP） |
| 前置依赖 | GenUI form 组件可用（Sprint 3 已交付）；日报 MVP + 交互优化 Sprint 已完成（73 个测试通过） |

---

## 3. Stories

> **承诺口径**：Must Stories（1–6，共 16 SP）是本 Sprint 的交付承诺；Should Story（7，2 SP）在 Must 完成后推进。

### Story 1（Must）：GenUI form 新增 `multi-select` 字段类型 — Zod schema 层（2 SP）

**目标**：让 GenUI validator 能识别和校验 `multi-select` 字段，解除渲染阻塞。

**范围**：

- `frontend/src/core/genui/validator.ts`：
  - `formFieldSchema.type` 枚举增加 `"multi-select"`
  - `options` schema 扩展 `group?: string` 和 `description?: string` 可选字段
  - `formFieldSchema` 增加 `searchable?: boolean` 和 `max_visible?: number` 可选字段

**验收标准**：

- `validateProps("form", ...)` 对包含 `type: "multi-select"` 的字段返回 `success: true`
- `options` 中的 `group` 和 `description` 字段通过校验
- 现有 9 种字段类型的校验行为不受影响
- 单元测试覆盖 multi-select 字段的合法/非法 props

**依赖**：无。

### Story 2（Must）：GenUI form 新增 `multi-select` 字段类型 — 渲染层（5 SP）

**目标**：在 FormBlock 中实现可搜索、可分组、可批量选择的 multi-select 控件。

**范围**：

- `frontend/src/components/genui/FormBlock.tsx`：
  - 从 `useForm()` 额外解构 `control`（现有代码只解构 `register`、`handleSubmit`、`formState`）
  - `defaultValues` 类型从 `Record<string, string>` 放宽为 `Record<string, unknown>`（支持 `string[]` 默认值，对现有字段无影响）
  - 新增 `MultiSelectField` 子组件（~150 行）
  - multi-select 分支使用 `<Controller>` 而非 `register()`（原因：multi-select 是自定义 React 组件，不是原生 HTML 元素，`register()` 无法绑定）
  - 搜索框：输入关键词实时过滤 options（匹配 `label`、`value`、`description`）
  - 分组：按 `option.group` 字段分区域展示，每组显示组名和设备数量
  - 全选/全不选：全局级别 + 每组级别
  - 选中计数：底部显示"已选 X / Y 台"
  - 滚动容器：`max_visible` 控制可视区域高度（默认 10 条），超出可滚动
  - 提交值：`string[]`（选中的 value 数组），通过 `Controller` 的 `field.onChange` 更新

**交互设计**：

```
┌─────────────────────────────────────────┐
│ 🔍 搜索设备ID或名称...                  │
├─────────────────────────────────────────┤
│ ☑ 全选 (1000)                           │
│                                         │
│ ▼ A区 (250)         [全选] [全不选]      │
│   ☑ SE-001  换热器-001                  │
│   ☑ SE-002  冷却器-002                  │
│   ... (滚动)                            │
│                                         │
│ ▼ B区 (250)         [全选] [全不选]      │
│   ☑ SE-251  换热器-251                  │
│   ...                                   │
│                                         │
│ 已选：1000 / 1000                       │
└─────────────────────────────────────────┘
```

**验收标准**：

- 1000 个 options 的表单能正常渲染，无卡顿（<500ms 首次渲染）
- 搜索输入实时过滤，300ms 内响应
- 分组折叠/展开正常工作
- 全选/全不选（全局 + 组级别）功能正确
- 提交后 `payload` 包含正确的 `string[]` 值
- 无 options 时显示"无数据"
- 与 react-hook-form 集成正确（使用 `Controller` 而非 `register()`、required 校验、disabled 状态）
- `defaultValues` 类型放宽不破坏现有字段（text/select/checkbox 行为不变）
- `GenUIRenderer` 能正确渲染 multi-select 表单（Zod 校验通过 → 组件加载 → 渲染 → 提交）

**依赖**：Story 1（Zod schema 必须先就位，否则 GenUIRenderer 会静默拒绝渲染）。

### Story 3（Must）：后端 Agent starters 配置能力（3 SP）

**目标**：让 AgentConfig 支持 `starters` 字段，数据能从 config.yaml 完整流转到前端 API 响应。

**范围**：

- `backend/packages/harness/deerflow/config/agents_config.py`：
  - 新增 `StarterConfig(BaseModel)`: `label: str`, `prompt: str`, `icon: str | None = None`, `auto_start: bool = False`
  - `AgentConfig` 增加 `starters: list[StarterConfig] | None = None`
  - `AgentInfo` 增加 `starters: list[StarterConfig] | None = None`
  - `to_agent_info()` 映射 `starters` 字段
- `backend/app/gateway/routers/agents.py`：
  - `AgentResponse` 增加 `starters: list[dict] | None = Field(default=None, ...)`
  - `_agent_config_to_response()` 映射 `starters`（`[s.model_dump() for s in cfg.starters] if cfg.starters else None`）
- `agents/builtin/ai-report--daily/config.yaml`：
  - 增加 `starters` 配置项

**三层模型数据流验证**：

```
config.yaml  →  AgentConfig.starters    ←  load_agent_config() 白名单包含 "starters"
                     ↓
             AgentResponse.starters     ←  _agent_config_to_response() 显式映射
                     ↓
             HTTP JSON .starters        ←  Pydantic 序列化输出
                     ↓
             Frontend Agent.starters    ←  TypeScript 类型声明
```

**验收标准**：

- config.yaml 中的 `starters` 不被 `known_fields` 白名单过滤丢弃
- `GET /api/agents` 响应 JSON 中日报 Agent 包含 `starters` 数组
- `starters[0].auto_start == true`
- 无 `starters` 配置的 Agent 返回 `starters: null`
- 单元测试覆盖 `StarterConfig` 序列化、`AgentConfig` 解析、`AgentResponse` 输出

**依赖**：无。

### Story 4（Must）：前端 starters 渲染与 auto_start 触发（3 SP）

**目标**：让 Agent 欢迎页显示 starter 快捷按钮，支持 `auto_start` 自动发送隐藏消息。

**范围**：

- `frontend/src/core/agents/types.ts`：
  - 新增 `StarterConfig` 类型：`{ label: string; prompt: string; icon?: string | null; auto_start?: boolean }`
  - `Agent` 接口增加 `starters?: StarterConfig[] | null`
- `frontend/src/components/workspace/agent-welcome.tsx`：
  - 接收 `onStarterClick?: (prompt: string) => void` prop
  - 当 `agent.starters` 非空时，渲染 `Suggestions` + `Suggestion` 按钮列表
  - 点击按钮调用 `onStarterClick(starter.prompt)`
- `frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx`：
  - 将 `onStarterClick` 连接到 `handleSubmit`
  - 新增 `useEffect`：当 `isNewThread && agent?.starters` 中存在 `auto_start: true` 的 starter 时，自动调用 `handleSubmit({ text: starter.prompt, files: [] })` 并传入 `additionalKwargs: { hide_from_ui: true }`
  - 使用 `useRef` 防止 StrictMode 双重触发

**验收标准**：

- 进入日报 Agent 新线程后，**无需手动输入**，自动发送隐藏消息触发 Agent
- 隐藏消息不在聊天记录中显示
- Agent 收到消息后立即渲染参数表单
- 无 `starters` 配置的 Agent 欢迎页行为不变
- 有 `starters` 但无 `auto_start` 的 Agent 只显示按钮，不自动发送
- `pnpm typecheck` 通过

**依赖**：Story 3（后端 API 必须返回 starters 数据）。

### Story 5（Must）：日报 Agent 设备选择集成（2 SP）

**目标**：将 multi-select 组件集成到日报表单流程，用户可以浏览和选择具体设备。

**范围**：

- `agents/builtin/ai-report--daily/SOUL.md`：
  - Round 1 表单简化：移除 `equipment_scope` 和 `scope_filter` 字段，只保留日期、设备类型、对比基准
  - 新增 Round 1.5（`callback_id: daily-report-equipment`）：调用 `list_equipment.py --limit 10000` 获取完整设备列表，渲染 multi-select 表单
  - Round 1.5 回调逻辑：从 `payload.equipment_ids` 读取选中设备，根据数量和区域覆盖判断走 `--equipment` 还是 `--scope` 路径
  - Round 2 KPI 选择不变
- `skills/custom/data-analyst/scripts/list_equipment.py`：
  - 返回值增加 `area_counts` 字段（`{"A区": 250, "B区": 250, ...}`）

**验收标准**：

- Round 1 表单不再包含"设备范围"和"区域/设备ID"字段
- 提交 Round 1 后看到设备多选表单（按区域分组，每台设备可见）
- 默认全选，用户可取消勾选
- 搜索设备ID/名称可快速过滤
- 提交设备选择后进入 KPI 选择（Round 2）
- 后续日报生成流程不受影响
- `list_equipment.py` 返回中包含 `area_counts`

**依赖**：Story 1 + 2（multi-select 组件就位）、Story 4（auto_start 触发表单）。

### Story 6（Must）：测试覆盖（2 SP）

**目标**：确保新增能力有充分测试。

**范围**：

- 前端单元测试：
  - 新建 `tests/unit/core/genui/validator.test.ts`：multi-select 字段 Zod 校验（合法/非法 props、group/description 扩展、searchable/max_visible）
  - 新建 `tests/unit/components/genui/FormBlock.test.tsx`：multi-select 渲染、搜索过滤、全选/全不选、Controller 集成、提交值为 `string[]`
- 后端单元测试：
  - `backend/tests/test_agents_config.py`（扩展）：`StarterConfig` 解析、`AgentConfig.starters` 序列化、`to_agent_info()` 映射
  - `backend/tests/test_ai_report_daily_list_equipment.py`（扩展）：`area_counts` 字段存在且正确
- `pnpm typecheck` + `pnpm check` 通过
- `make test`（后端）通过

**验收标准**：

- Zod schema 测试覆盖 multi-select 的合法和非法输入
- `StarterConfig` 测试覆盖 yaml 解析、白名单不丢弃、API 响应包含
- `area_counts` 测试覆盖各设备类型
- 现有 73 个日报测试不受影响
- 无回归

**依赖**：Story 1、2、3、5。

### Story 7（Should）：multi-select 虚拟滚动优化（2 SP）

**目标**：当设备数量 > 2000 时，使用虚拟滚动避免 DOM 节点过多导致卡顿。

**范围**：

- `FormBlock.tsx` 的 `MultiSelectField`：
  - 当 `options.length > 500` 时启用虚拟滚动（`@tanstack/react-virtual` 或原生 `IntersectionObserver`）
  - 每组内仅渲染可见区域的 checkbox

**验收标准**：

- 5000 个 options 的表单首次渲染 < 300ms
- 滚动流畅无卡顿
- 搜索过滤后虚拟列表正确更新
- < 500 个 options 时不启用虚拟滚动，行为不变

**依赖**：Story 2。

---

## 4. 不建议本 Sprint 承诺的内容

### 真实设备 API 对接

**原因**：设备数据来自外部系统，具体 API 接口和数据 schema 未确定。当前使用 `list_equipment.py` 演示数据验证交互流程。

**建议**：本 Sprint 验证 multi-select 交互可行性，真实 API 接入放到下个 Sprint。

### multi-select 异步加载（分页/懒加载）

**原因**：当前 GenUI form 是一次性渲染所有 options（由 Agent 在 `render_ui` 时一次传入）。异步加载需要新增前端 ↔ 后端的分页协议，改动面大。

**建议**：Story 7 的虚拟滚动能覆盖 5000 台以内的场景。超过 5000 台的异步加载放到 GenUI 组件增强迭代。

### 其他 Agent 的 starters 配置

**原因**：`starters` 是通用能力，但本 Sprint 只为日报 Agent 配置。其他 Agent 的 starter 内容需要逐个确认。

**建议**：本 Sprint 只配置日报 Agent，验证通用性后其他 Agent 在后续 Sprint 中按需配置。

---

## 5. 依赖关系图

```
Story 1 (Zod schema) ──→ Story 2 (渲染层) ──→ Story 5 (日报集成) ──→ Story 6 (测试)
                                            ↗                          ↑
Story 3 (后端 starters) → Story 4 (前端 starters) ─────────────────────┘
                                                                       ↑
                         Story 2 ──→ Story 7 (虚拟滚动, Should)        │
```

**关键路径**：Story 1 → Story 2 → Story 5 → Story 6

**可并行**：
- Story 1 + Story 3 可在 Day 1 同时开始（无依赖）
- Story 2 + Story 4 可在 Day 2 同时开始（各自前置已完成）

---

## 6. Sprint Sequencing

```
Day 1（后端 + Schema 层）
├── Story 1：validator.ts Zod schema 扩展（multi-select 字段类型）
├── Story 3：后端 StarterConfig + AgentConfig + AgentResponse + config.yaml
└── list_equipment.py 增加 area_counts

Day 2（前端组件层）
├── Story 2：FormBlock multi-select 渲染（搜索、分组、全选、滚动）
└── Story 4：前端 Agent 类型扩展 + AgentWelcome starters + auto_start

Day 3（集成联调）
├── Story 5：改写 SOUL.md（Round 1 简化、Round 1.5 设备选择、回调逻辑）
├── 联调：auto_start → 表单渲染 → multi-select → 设备选择 → KPI 选择 → 日报生成
└── 验证完整链路（1000 台设备场景）

Day 4（测试 + 打磨）
├── Story 6：前端 Zod 单元测试 + 后端 StarterConfig 测试 + area_counts 测试
├── 回归测试：73 个日报测试 + pnpm typecheck + pnpm check
└── Bug 修复

Day 5（缓冲 + Stretch）
├── Bug 修复 + 边界场景测试
├── Story 7（Should）：虚拟滚动优化（如时间允许）
└── 更新设计文档
```

---

## 7. 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| multi-select 1000+ options 导致首次渲染卡顿 | 中 | 高 | Story 2 中先用简单 CSS overflow 滚动；Story 7 作为 Stretch 补充虚拟滚动 |
| Zod schema 扩展导致现有 form 校验回归 | 低 | 高 | Story 1 中先跑现有 form 测试确认无回归，再增加 multi-select 测试 |
| `auto_start` 在 React StrictMode 下双重触发 | 中 | 中 | Story 4 使用 `useRef` 守卫，确保只触发一次 |
| payload 体积（1000 台设备 ~15KB） | 低 | 低 | 当前规模无问题；> 5000 台时需考虑压缩策略，记入技术债 |
| `AgentResponse` 遗漏 `starters` 字段导致前端收不到数据 | — | 阻塞 | Story 3 验收标准明确要求 API 响应验证，CI 中加测试 |
| `formFieldSchema` 白名单未更新导致 multi-select 表单不渲染 | — | 阻塞 | Story 1 是最高优先级，Day 1 第一件事完成 |

---

## 8. Sprint Summary

```
Sprint Goal:
让日报用户点击即开始、可视化选择每一台设备，消除手动输入消息和设备ID的交互痛点。

Duration:
1 周

Team Capacity:
5 人天，预留 20% 缓冲后可承诺 4 人天 / 16 SP

Must Stories（承诺，共 16 SP）:
1. GenUI multi-select Zod schema 层 — 2 SP
2. GenUI multi-select 渲染层 — 5 SP
3. 后端 Agent starters 配置能力 — 3 SP
4. 前端 starters 渲染与 auto_start — 3 SP
5. 日报 Agent 设备选择集成 — 2 SP
6. 测试覆盖 — 2 SP（跨所有 Stories）

Should / Stretch Stories（容量允许时推进，共 2 SP）:
7. multi-select 虚拟滚动优化 — 2 SP

不承诺范围:
- 真实设备 API 对接（依赖外部接口定稿）
- multi-select 异步分页加载（依赖 GenUI 协议扩展）
- 其他 Agent 的 starters 配置（待日报验证通用性后按需添加）

前置依赖（已完成）:
- GenUI 基础设施（Sprint 1–4 已交付）
- 日报 MVP + 交互优化（73 个测试全部通过）
- PDF 导出、per-area 趋势图、present_files 集成（本次会话已完成）
```
