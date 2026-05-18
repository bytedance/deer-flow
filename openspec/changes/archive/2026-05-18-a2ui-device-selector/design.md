## Context

当前 A2UI 组件库已注册 16 个组件（chart, table, form 等），均为展示型或简单交互组件，缺少树形设备选择能力。Organize 组织树接口 `/organize/getOrgTreeByUserIdAndOrgId` 已由 ins-bus-rpc 微服务提供，返回嵌套的组织设备树结构。前端栈：Next.js 16 + React 19 + TypeScript 5.8 + Tailwind CSS 4，无 antd 依赖。

约束：组件必须遵循现有 A2UI 三文件注册模式（registry.ts + sanitizer.ts + validator.ts）；交互组件须复用 `onInteraction` 回调机制。

## Goals / Non-Goals

**Goals:**
- 新增 `device-selector`（单选）和 `device-selector-multi`（多选）两个 A2UI 交互组件
- 左右分栏布局：左侧展示组织树（可折叠文件夹式导航），右侧展示选中组织节点下的设备列表（可选择）
- type>=10 的节点为组织节点，在左侧树中作为文件夹展示；type<10 的节点为设备节点，在右侧列表中展示
- 选中后通过 `onInteraction` 回调回传选中设备的 id / label / type
- 后端新增 `OrganizeServiceClient` 封装 organize 组织树 API
- 组件通过 props 接收预取的树形数据（由后端在构建 UIBlock 时注入）

**Non-Goals:**
- 不做树节点的动态懒加载（一次性加载完整树）
- 不实现节点拖拽、排序
- 不实现设备节点的增删改
- 不做搜索过滤功能（第一版）

## Decisions

### 1. 两个独立组件 vs 一个组件 + mode 参数

选择两个独立组件 `device-selector` 和 `device-selector-multi`。理由：
- 遵循用户明确要求"单选多选是不同的组件"
- 交互逻辑差异显著（单选点击替换选中 → 回传单个对象；多选 toggle 选中 → 回传数组）
- 状态管理和回传 payload 结构不同，拆分为两个组件更内聚，避免内部分支

### 2. 树数据来源：props 注入 vs 组件内 fetch

选择 props 注入（由后端在构建 UIBlock 时预取树数据放入 props）。理由：
- 符合现有 A2UI 组件模式：组件为纯前端渲染层，数据由后端提供
- 避免前端直接依赖 ins-bus-rpc 服务地址
- 后端可在构建 UIBlock 时做数据裁剪、缓存

### 3. 布局方案：左右分栏

```
┌──────────────────────────────────────────────┐
│  [标题]                                       │
│  ┌──────────────┬───────────────────────────┐ │
│  │  组织树       │  设备列表                  │ │
│  │              │                           │ │
│  │  ▼ 因思科技   │  ○ TMP装置 (旋转机组)      │ │
│  │  ▼ 海科瑞林   │  ○ 15万吨液化气 (旋转机组) │ │
│  │  ▶ 大机组系统 │  ○ 润滑油联产芳烃(旋转机组)│ │
│  │  ▼ 机泵系统   │                           │ │
│  │    ▼ 运行一部 │                           │ │
│  │    ▶ 运行二部 │                           │ │
│  │              │                           │ │
│  └──────────────┴───────────────────────────┘ │
└──────────────────────────────────────────────┘
```

**左侧**：可折叠组织树，只展示 type>=10 的组织节点作为文件夹。点击组织节点 → 展开/折叠子组织节点，同时右侧更新为该组织节点下包含的 type<10 设备列表。

**右侧**：
- 单选模式：设备以列表项展示，点击即选中并立即回传（高亮当前选中项）
- 多选模式：设备以复选框列表展示，勾选/取消勾选 + 底部计数 + 提交按钮

### 4. 树 UI 实现：自定义 + Tailwind

选择自定义可折叠树，使用纯 Tailwind CSS 实现。理由：
- 项目无 antd 依赖，不引入重型 UI 库
- 组织树层级通常不超过 5 层，自定义实现复杂度可控
- 与现有 shadcn/ui + Tailwind 风格一致

### 5. 组件 props 设计

`device-selector` props：
- `treeData: OrgTreeNode[]` — 完整组织设备树（必填）
- `title?: string` — 选择器标题

`device-selector-multi` props：同上
- 额外 `maxSelect?: number` — 最大可选数量

回调 payload：
- 单选：`{ selected: { id, label, type, path } }`
- 多选：`{ selected: [{ id, label, type, path }] }`

### 6. 后端 OrganizeServiceClient

在 `backend/packages/harness/deerflow/rpc/organize_service.py` 新增，遵循 `MachineServiceClient` 相同模式：
- `SERVICE_NAME = "ins-bus-rpc"`
- `PATH_PREFIX = "/ins-bus-rpc/organize"`
- 方法 `get_org_tree_by_user_id_and_org_id(user_id, org_id, tree_type, content?, hidden_if_valid?, if_add_overview_count?, view_id?, type_id?)`

### 7. 树节点接口定义

```typescript
interface OrgTreeNode {
  id: string;
  label: string;
  type: number;
  path: string;
  parentId: string;
  displayOrder?: number;
  hiddenFlag?: number;
  authFlag?: boolean;
  children?: OrgTreeNode[];
}
```

左侧树：递归遍历 treeData，仅渲染 type>=10 的节点（组织节点），type<10 的节点不直接出现在左侧树中而是归属到其父组织节点下，在右侧面板展示。

右侧设备列表：收集当前选中组织节点及其子孙中所有 type<10 的节点，按 displayOrder 排序展示。

## Risks / Trade-offs

- [风险] 树节点过多（数百个）导致渲染性能问题 → 缓解：第一版不做虚拟滚动，后续按需优化；组织树深度有限（<5层）
- [风险] 单选组件选中后回传立即触发 onInteraction，用户无法撤销 → 缓解：采用设计意图——选中即确认，符合设备选择器场景；如需撤销可重新点击右侧另一设备
- [取舍] 树数据一次性加载而非懒加载 → 组织树节点数量可控（数百级），全量加载更简单
- [取舍] 右侧设备列表不做分页 → 单个组织节点下设备数量通常不超过百级，全量展示即可
