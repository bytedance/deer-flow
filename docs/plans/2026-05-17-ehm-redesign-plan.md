# EHM AI 工作台 视觉与品牌改造方案（重写版）

- 日期：2026-05-17
- 状态：方案待评审（取代 2026-05-17-ehm-redesign-plan.md 的 v1）
- 范围：**仅前端样式 + 品牌门面**，业务能力零侵入
- 目标：把 DeerFlow 改造为面向**石油石化设备健康管理（EHM）**的 AI 工作台
- 关联评估：[.gstack/design-reports/design-audit-deerflow-ehm-2026-05-17.md](../../.gstack/design-reports/design-audit-deerflow-ehm-2026-05-17.md)

---

## 0. 设计原则（铁律）

> **所有业务能力都走后端 agent / skill / GenUI，前端只做样式与品牌。**

具体含义：

1. ❌ 前端**不**新增 EHM 业务页面（不做 `/ehm/overview`、`/ehm/alarms`、`/ehm/equipment`…）
2. ❌ 前端**不**新增 EHM 业务组件（不做 `<HealthIndexRing>`、`<AlarmBar>`、`<EquipmentTree>`…）
3. ❌ 前端**不**直连 OPC UA / 时序库 / 报警流（不写 `core/ehm/`）
4. ✅ **业务流通过 agent 对话 + skill 调用 + GenUI block 输出实现**
5. ✅ 前端**仅动样式层**（`globals.css`、字体、品牌门面、Welcome 文案、合规底线）
6. ✅ 必要的工业可视化能力，作为**通用 GenUI block** 加进 registry（如 `gauge`、`alarm`、`engine-number`），属于框架增强不是 EHM 专属

DeerFlow 的核心价值是 super-agent harness — 我不能为了行业适配把 harness 废掉。

---

## 1. 现状梳理（关键事实）

### 1.1 后端已有的 EHM skill（[skills/custom/](skills/custom/)）

| Skill | 作用 |
|---|---|
| `ins-device-analysis` | 设备综合分析 |
| `ins-extract-orbit-centerline-features` | 轴心轨迹特征提取 |
| `ins-extract-spectral-waveform-features` | 频谱/波形特征提取 |
| `ins-extract-trend-features` | 趋势特征提取 |
| `ins-get-orbit-data` | 轴心轨迹数据查询 |
| `ins-get-trend-data` | 趋势数据查询 |
| `ins-get-waveform-data` | 波形数据查询 |
| `vibration-fault-diagnosis` | 振动故障诊断 |
| `data-analyst` | 通用数据分析 |

业务能力**已经存在于 agent 侧**。前端的工作不是再造一遍。

### 1.2 前端已有的 GenUI 渲染机制

[frontend/src/core/genui/registry.ts](frontend/src/core/genui/registry.ts) 注册了 11 种通用 block：

```
chart  echart  table  card  form  confirm  code  timeline  layout  markdown  image
```

后端 skill 通过流式输出 GenUI block，前端通过 registry 自动渲染。**这是正确的扩展点**。

### 1.3 已设计的日报功能

`docs/plans/2026-05-16-daily-report-visual-and-interaction-design.md` 已经走的就是这个路径——**Markdown 文档 + 内嵌 SVG 图表**，由 agent 生成，前端只渲染。这是榜样。

### 1.4 真正需要前端动的地方

| 类别 | 现状 | 应该 |
|---|---|---|
| 样式基底 | DeerFlow 通用主题 | 工业主题（中性灰、报警色板） |
| 品牌门面 | DeerFlow / 鹿头 / Galaxy 星空 | EHM 品牌 / 工业视觉 |
| 字体 | 系统字体回退 | 自托管 Inter + Noto Sans SC |
| 合规 | --ring transparent / 无 reduced-motion / 无 tabular-nums | 全部修复 |
| Workspace placeholder | "Vibe Coding / Generate Songs / 哆啦A梦" | 工业语境占位文案 |
| GenUI 工业可视化原子 | 缺 gauge / alarm-strip / engine-number | 作为通用 block 补齐 |

**就这 6 类。**

---

## 2. 改造分期

| 阶段 | 周期 | 关键产出 |
|---|---|---|
| **P0 合规底线** | 0.5 天 | --ring 修复 / prefers-reduced-motion / tabular-nums / 5 级报警色板 CSS 变量 |
| **P1 工业主题** | 1 天 | `industrial-dark` + `industrial-light` 主题作为默认 |
| **P2 品牌完全替换** | 1–2 天 | 着陆页 / 登录页 / Header / Footer / Welcome / page metadata 全部 EHM，删 DeerFlow 视觉资产 |
| **P3 字体与文案** | 0.5 天 | 自托管 Inter + Noto Sans SC；Workspace 占位文案改工业语境；删 emoji 招手 / Confetti / golden-text |
| **P4 通用工业 GenUI block** | 3–5 天 | 在 registry 注册 `gauge`、`alarm-strip`、`engine-number`、`status-chip`，作为通用块；后端 skill 自由调用 |

**总周期：1 周（CC + gstack）。** 比 v1 方案的 3–4 周大幅压缩，因为业务都走 agent。

> 不设"装置选择器"。用户直接在对话里描述设备（例如"P-101A 最近 24 小时振动如何？"），agent 通过 skill 解析 / 查询 / 应答；选择器是消费 SaaS 思维下的"导航即业务"，与本方案"业务全在 agent 对话流"原则冲突。

---

## 3. P0 合规底线（半天，可独立 PR）

> 这一步与 EHM 无关，是上游 DeerFlow 本来就该修的合规底线。EHM 在此基础上叠加。

### 3.1 修焦点环

`frontend/src/styles/globals.css`：

```diff
:root {
-  --ring: transparent;
+  --ring: oklch(0.55 0.15 230);  /* 工业蓝 */
}
.dark {
-  --ring: transparent;
+  --ring: oklch(0.7 0.15 230);
}
```

### 3.2 加 `prefers-reduced-motion`

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
  .galaxy-container,
  [class*="ambilight"],
  [class*="aurora"] {
    display: none !important;
  }
}
```

### 3.3 数字默认 tabular-nums

```css
@layer base {
  body {
    font-variant-numeric: tabular-nums;
  }
}
```

### 3.4 注入工业语义色 CSS 变量

```css
:root {
  /* 5 级报警 — IEC 62682 / ISA-18.2 */
  --alarm-critical:  oklch(0.45 0.20 320);
  --alarm-high:      oklch(0.60 0.22 25);
  --alarm-medium:    oklch(0.78 0.18 90);
  --alarm-low:       oklch(0.65 0.20 350);
  --alarm-journal:   oklch(0.65 0.15 230);

  /* 6 状态 */
  --status-running:  oklch(0.55 0.10 145);
  --status-stopped:  oklch(0.55 0.00 0);
  --status-maint:    oklch(0.65 0.15 60);
  --status-standby:  oklch(0.65 0.10 230);
  --status-fault:    oklch(0.55 0.22 25);
  --status-comm-loss: oklch(0.50 0.05 260);
}
```

并在 Tailwind v4 的 `@theme inline` 暴露 `--color-alarm-*` 与 `--color-status-*`，使 `bg-alarm-high` 等类生效。**后端 skill 输出的 GenUI block 直接用这些类**，前后端解耦。

### 3.5 P0 验收

- [ ] Tab 键能看到焦点环
- [ ] 系统"减少动效"开启后 Galaxy/Aurora/Flicker 全消失
- [ ] 任意表格数字位宽对齐
- [ ] `<div class="bg-alarm-critical text-foreground">` 上色正确

---

## 4. P1 工业主题（1 天）

### 4.1 新增 industrial 主题（与 light/dark 并存）

```css
:root[data-theme="industrial-dark"] {
  --background: oklch(0.22 0 0);    /* ISA-101 中性深灰 */
  --foreground: oklch(0.92 0 0);
  --card: oklch(0.27 0 0);
  --primary: oklch(0.55 0.15 230);  /* 工业蓝 */
  --secondary: oklch(0.30 0 0);
  --muted: oklch(0.30 0 0);
  --muted-foreground: oklch(0.65 0 0);
  --border: oklch(0.35 0 0);
  --ring: oklch(0.55 0.15 230);
  --radius: 0.375rem;               /* 6px：工业小圆角 */
}

:root[data-theme="industrial-light"] {
  --background: oklch(0.93 0 0);
  --foreground: oklch(0.20 0 0);
  --card: oklch(0.97 0 0);
  --primary: oklch(0.40 0.15 230);
  --border: oklch(0.78 0 0);
  --ring: oklch(0.40 0.15 230);
  --radius: 0.375rem;
}
```

### 4.2 默认主题改为 industrial-dark

`frontend/src/app/layout.tsx` 在 `<ThemeProvider>` 上把 `defaultTheme` 改为 `"industrial-dark"`。

### 4.3 设置页主题选项

`appearance-settings-page.tsx` 暴露 4 个选项：light / dark / industrial-dark / industrial-light。控制室常态用 industrial-dark，办公室用 industrial-light。

> 后端 skill 输出的 chart 颜色必须**走 CSS 变量**而不是写死 hex。这要求 skill 侧约定（在 [skills/custom/CONTRIBUTING.md](skills/custom/) 里加一条规范）。

---

## 5. P2 品牌完全替换（1–2 天，删 DeerFlow）

### 5.1 删除的视觉资产 / 组件用法

直接从代码里删除以下使用点（组件本身保留，可能被开发者文档复用，但 EHM 主线不再引用）：

| 文件 | 删除内容 |
|---|---|
| `landing/hero.tsx` | Galaxy、FlickeringGrid、WordRotate、BytePlusIcon、鹿头蒙版 |
| `landing/header.tsx` | 鹿头 logo、粉紫渐变光晕、GitHub Star 按钮 |
| `landing/footer.tsx` | "Originated from Open Source... © DeerFlow" |
| `landing/sections/case-study-section.tsx` | 6 个消费 AI 案例（哆啦A梦/泰坦尼克/PnP）|
| `landing/sections/skills-section.tsx` | "Agent Skills" 通用文案 |
| `landing/sections/sandbox-section.tsx` | "AIO Sandbox" 等开发者向叙事 |
| `landing/sections/whats-new-section.tsx` | DeerFlow 2.0 升级文案 |
| `landing/sections/community-section.tsx` | "Star on GitHub" / "Contribute Now" |
| `workspace/welcome.tsx` | `👋` 招手、`AuroraText` |
| `workspace/input-box.tsx` | `ConfettiButton`（撒纸屑 surprise me）、`golden-text`（Ultra 模式金字） |
| `app/(auth)/login/page.tsx` | `<h1>DeerFlow</h1>`、鹿头 mask FlickeringGrid |
| `globals.css` | `.ambilight` 彩虹环境光、`.golden-text`、`--animate-aurora`、`--animate-shine`、`--animate-wave`、`@keyframes ambilight` |
| `app/layout.tsx` 的 `metadata` | title / description / og:image 全部 EHM |
| `public/images/deer.svg`、`public/images/{caseStudy}.jpg` | 删除资产文件 |
| `core/i18n/messages/{en-US,zh-CN}/*` | 所有 "DeerFlow"、"Welcome to DeerFlow" 等文案改 EHM |
| `next.config` | `metadataBase` 域名改 EHM 域 |

### 5.2 重写的关键页面

| 页面 | 新内容 |
|---|---|
| `app/page.tsx`（着陆页） | Hero："设备健康管理 AI 工作台" + 副标题 + "进入工作台"主 CTA。下方板块：业务能力概览（4 列文字网格，无装饰）、合规与安全、技术底座（一句话提及"基于 super-agent 架构"，不提 DeerFlow）。**完全静态、无 WebGL、无装饰动效。** |
| `app/(auth)/login/page.tsx` | `<h1>EHM AI 工作台</h1>` 等。背景从鹿头闪烁网格改为静态 SVG 工业图样（管线/反应器轮廓极淡水印）或纯色。Login form 不变。 |
| `components/workspace/welcome.tsx` | 静态欢迎："欢迎，{user_name}。" 无 emoji、无 Aurora。不显示"当前装置"——用户在对话里直接讲。 |
| `components/workspace/input-box.tsx` SuggestionList | 占位提示语全部换工业语境（详见 §6.2） |
| `components/workspace/workspace-header.tsx` | logo + breadcrumb，logo 用 EHM 工作台 logo |

### 5.3 不删，但隔离

`landing/hero.tsx`、`Galaxy`、`FlickeringGrid`、`AuroraText`、`ConfettiButton` 这些组件**文件保留**（避免 lint 失败、有人 import 就坏掉），但 EHM 主线不再使用。如果未来要做 dev/demo 模式可以再启用。

### 5.4 i18n

EHM 是国内为主，把 `core/i18n/locale.ts` 默认 locale 改为 `zh-CN`。英文版同步更新（后续国际化考虑英文术语）。

---

## 6. P3 字体与文案（半天）

### 6.1 字体自托管

新建 `frontend/src/app/fonts.ts`：

```ts
import { Inter, Noto_Sans_SC, JetBrains_Mono } from "next/font/google";

export const fontSans = Inter({
  subsets: ["latin"], display: "swap", variable: "--font-sans-latin",
});
export const fontCJK = Noto_Sans_SC({
  subsets: ["latin"], display: "swap", variable: "--font-sans-cjk",
  weight: ["400", "500", "600", "700"],
});
export const fontMono = JetBrains_Mono({
  subsets: ["latin"], display: "swap", variable: "--font-mono",
});
```

`globals.css`：

```css
--font-sans: var(--font-sans-latin), var(--font-sans-cjk), ui-sans-serif, system-ui, sans-serif;
--font-mono: var(--font-mono), ui-monospace, monospace;
```

如果客户内网完全禁外联，把字体 woff2 下载到 `public/fonts/`，改用 `next/font/local`。

### 6.2 Workspace 占位文案（i18n）

`core/i18n/messages/zh-CN/inputBox.ts` 之类的位置：

| 字段 | 旧 | 新 |
|---|---|---|
| placeholder | "Ask DeerFlow anything..." | "请描述您要分析的设备问题（含位号）……" |
| surpriseMe | "Surprise me" | 删除（工业产品不需要） |
| suggestions | 通用问题 | "P-101A 最近 24 小时振动趋势如何？" / "查询 C-201 频谱特征" / "生成今日装置运行日报" / "诊断 K-301 异常根因" |
| flashMode 描述 | "Quickly answer..." | "快速查询：实时数据、单点状态" |
| reasoningMode 描述 | "Think step by step..." | "推理诊断：故障根因、退化趋势" |
| proMode 描述 | "Plan ahead..." | "深度分析：多测点关联、SOP 推荐" |
| ultraMode 描述 | "Spawn sub-agents..." | "多 agent 协同：复杂诊断、综合日报" |

> 这些 suggestion 触发的还是后端 skill（vibration-fault-diagnosis 等），前端没新代码。

### 6.3 删装饰

`globals.css` 删 `.golden-text`、`.ambilight`；`input-box.tsx` 删 `ConfettiButton`、删 `golden-text` 类引用。`welcome.tsx` 删 `animate-wave`、`AuroraText`。

---

## 7. P4 通用工业 GenUI block（3–5 天）

> 这是唯一新增组件的地方，但**关键定位是"通用 GenUI 块"**，不是"EHM 专用组件"。任何 skill 都能用，跟 chart/table/card 是同一层抽象。

### 7.1 新增 4 个通用 block

注册到 [frontend/src/core/genui/registry.ts](frontend/src/core/genui/registry.ts)：

```diff
const COMPONENT_REGISTRY: Record<string, () => Promise<{ default: LazyComponent }>> = {
   chart: () => import("@/components/genui/ChartBlock") as any,
   echart: () => import("@/components/genui/EChartBlock") as any,
   table: () => import("@/components/genui/TableBlock") as any,
   card: () => import("@/components/genui/CardBlock") as any,
   form: () => import("@/components/genui/FormBlock") as any,
   confirm: () => import("@/components/genui/ConfirmBlock") as any,
   code: () => import("@/components/genui/CodeBlock") as any,
   timeline: () => import("@/components/genui/TimelineBlock") as any,
   layout: () => import("@/components/genui/LayoutBlock") as any,
   markdown: () => import("@/components/genui/MarkdownBlock") as any,
   image: () => import("@/components/genui/ImageBlock") as any,
+  gauge: () => import("@/components/genui/GaugeBlock") as any,
+  alarm: () => import("@/components/genui/AlarmBlock") as any,
+  metric: () => import("@/components/genui/MetricBlock") as any,
+  status: () => import("@/components/genui/StatusBlock") as any,
};
```

| Block | 作用 | 输入 schema（后端 skill 产出） |
|---|---|---|
| **gauge** | 0–100 指数环 / 量程指示器 | `{ value, min?, max?, thresholds?, unit?, label? }` |
| **alarm** | 单条/列表式报警栏（5 级颜色） | `{ items: [{level, message, time, source, ack?}] }` |
| **metric** | 工程读数：数值 + 单位 + 量程 + 偏差 | `{ tag, value, unit, range?, setpoint?, delta?, status? }` |
| **status** | 6 状态徽章 | `{ status: running\|stopped\|maint\|standby\|fault\|comm-loss, label? }` |

每个 block：
- ≤ 200 行
- 用 P0 注入的 CSS 变量上色（`bg-alarm-high` 等），不写死颜色
- 支持 loading / empty / error / **stale**（数据失联）四态
- 默认 `tabular-nums`
- `useReducedMotion` 时静态显示

### 7.2 后端 skill 怎么用

举例：`vibration-fault-diagnosis` skill 在判定故障后输出：

```json
{ "type": "alarm", "version": "1.0", "props": {
  "items": [
    { "level": "high", "message": "P-101A 轴承内圈频带能量异常", "time": "2026-05-17T08:14:00Z", "source": "TAG-VIB-101A-X" }
  ]
}}
{ "type": "gauge", "version": "1.0", "props": {
  "value": 4.8, "min": 0, "max": 10, "thresholds": { "warn": 4.5, "error": 7.1, "critical": 9.0 },
  "unit": "mm/s", "label": "P-101A 振动有效值"
}}
{ "type": "markdown", "version": "1.0", "props": { "content": "## 诊断结论\n..." }}
```

前端零修改、自动渲染。**这就是 GenUI 的正确用法。**

### 7.3 测试与文档

- [ ] 每个 block 的 vitest 单测覆盖率 ≥ 80%
- [ ] 在 [docs/genui-blocks.md](docs/) 增补 4 个 block 的 schema 文档（后端 skill 作者参考）
- [ ] 更新 `frontend-design` skill（`skills/public/frontend-design/`），告诉 agent "需要展示工业读数时优先用 gauge/alarm/metric/status block"

---

## 8. 不做装置选择器（明确决策）

**用户不在 UI 上选择厂区/装置/机组**。理由：

1. 选择器是消费 SaaS 思维下的"导航即业务"，本方案的核心是**业务全在 agent 对话里发生**。一旦前端做选择器，就要做"已选装置展示"、"切换装置时清状态"、"选择器与对话上下文同步"等一连串状态管理——这些都是业务耦合。
2. 用户能直接说"P-101A 振动趋势"、"看一下 K-301 频谱"，agent 通过 skill 自然语言解析位号即可。这比下拉级联更快、更符合 AI 工作台的交互形态。
3. 如果某些 skill 确实需要装置上下文（比如批量日报），由 skill 自己在对话里发起 form block 询问，而不是在全局 chrome 上长期占位。

**前端职责**：一个干净的对话工作台 + 工业风格视觉。**后端职责**：理解用户讲的设备/位号、调对应 skill、产出 GenUI block。

---

## 9. 文件改动清单（总览）

```
新建（≤ 8 个文件）：
  frontend/src/app/fonts.ts                      ← 字体自托管
  frontend/src/components/genui/GaugeBlock.tsx   ← 通用 gauge block
  frontend/src/components/genui/AlarmBlock.tsx   ← 通用 alarm block
  frontend/src/components/genui/MetricBlock.tsx  ← 通用 metric block
  frontend/src/components/genui/StatusBlock.tsx  ← 通用 status block
  frontend/tests/unit/genui/{gauge,alarm,metric,status}.test.tsx
  docs/genui-blocks.md                           ← block schema 文档

修改：
  frontend/src/styles/globals.css                ← P0 + P1 + P3 删装饰
  frontend/src/core/genui/registry.ts            ← 注册 4 新 block
  frontend/src/app/layout.tsx                    ← metadata + 字体 + 默认主题
  frontend/src/app/page.tsx                      ← 重写为 EHM 着陆页
  frontend/src/app/(auth)/login/page.tsx         ← 改 EHM 品牌
  frontend/src/components/landing/hero.tsx       ← 删 Galaxy/FlickeringGrid/WordRotate（或整个文件不再被引用）
  frontend/src/components/landing/sections/*     ← 全部重写或不再引用
  frontend/src/components/landing/header.tsx     ← 改 EHM
  frontend/src/components/landing/footer.tsx     ← 改 EHM
  frontend/src/components/workspace/welcome.tsx  ← 静态欢迎
  frontend/src/components/workspace/input-box.tsx ← 删 ConfettiButton/golden-text
  frontend/src/components/workspace/settings/appearance-settings-page.tsx ← 4 主题选项
  frontend/src/core/i18n/messages/zh-CN/*        ← 文案
  frontend/src/core/i18n/messages/en-US/*        ← 文案
  frontend/CLAUDE.md                             ← 更新设计说明
  next.config                                    ← metadataBase

删除：
  frontend/public/images/deer.svg
  frontend/public/images/{6 个 caseStudy thread_id}.jpg

完全不动：
  frontend/src/components/ai-elements/*          ← 上游生成代码
  frontend/src/components/ui/*                   ← shadcn 主干
  frontend/src/core/threads/*
  frontend/src/core/api/*
  frontend/src/core/skills/*
  frontend/src/core/agents/*
  frontend/src/core/memory/*
  frontend/src/core/mcp/*
  backend/**                                     ← 业务都在后端 agent
```

**前端业务零侵入。** 后端 skill 想加任何能力，自己产出对应 GenUI block 就行，不需要前端发版。

---

## 10. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 后端 skill 输出旧 hex 颜色，工业主题下不协调 | 在 `skills/custom/CONTRIBUTING.md` 加一条规范："chart 颜色必须用 `var(--color-*)` 而非 hex"；GenUI sanitizer 给个迁移期警告 |
| 4 个新 block 的 schema 不稳定 | P4 先做 `gauge` + `alarm` 两个最常用的；`metric`、`status` 用现有 `card` 凑合一段时间，schema 稳了再加 |
| 国产化内网无法连 Google Fonts | 提供 `next/font/local` 备选 + 把 woff2 放 `public/fonts/` |
| EHM 主题与上游 light/dark 同步维护成本 | industrial-* 写在独立 selector，仅靠 CSS 变量增量；上游升级不冲突 |
| 用户切回 light/dark 看到 chart 颜色错乱 | 所有颜色变量四套主题都给值，覆盖完整 |

---

## 11. 与 v1 方案的差异对比

| 维度 | v1（已废弃） | v2（本文） |
|---|---|---|
| 业务页面 | 新建 9 个 EHM 页面 | **0 个**（业务在对话流） |
| 业务组件 | 13 个 EHM 专用组件 | **4 个通用 GenUI block** |
| 业务数据层 | `core/ehm/` 直连后端 | **0 个**（agent 调 skill） |
| AI 助理形态 | 各页面右侧抽屉 | 主舞台保持不变（chat workspace） |
| 多窗格容器 | `<ConsoleGrid>` | **不需要**（一个 thread 里多个 GenUI block 自然就是多窗格） |
| 周期 | 3–4 周 | **1 周** |
| 业务耦合 | 重 | **零** |
| 上游升级风险 | 中 | **极低**（只动样式与品牌门面） |

---

## 12. 一句话总结

> **业务都在 agent + skill + GenUI 里，前端只换皮、补合规、加 4 个通用工业块。一周可上线。**

---

## 附录 A — P0 + P3 的最小补丁（< 100 行 diff，今天可合并）

```diff
--- a/frontend/src/styles/globals.css
+++ b/frontend/src/styles/globals.css
@@ -244,1 +244,1 @@
-  --ring: transparent;
+  --ring: oklch(0.55 0.15 230);
@@ -278,1 +278,1 @@
-  --ring: transparent;
+  --ring: oklch(0.7 0.15 230);
@@ +295 layer base
 @layer base {
   * { @apply border-border outline-ring/50; }
-  body { @apply bg-background text-foreground; }
+  body {
+    @apply bg-background text-foreground;
+    font-variant-numeric: tabular-nums;
+  }
+
+  :root {
+    --alarm-critical:  oklch(0.45 0.20 320);
+    --alarm-high:      oklch(0.60 0.22 25);
+    --alarm-medium:    oklch(0.78 0.18 90);
+    --alarm-low:       oklch(0.65 0.20 350);
+    --alarm-journal:   oklch(0.65 0.15 230);
+    --status-running:  oklch(0.55 0.10 145);
+    --status-stopped:  oklch(0.55 0.00 0);
+    --status-maint:    oklch(0.65 0.15 60);
+    --status-standby:  oklch(0.65 0.10 230);
+    --status-fault:    oklch(0.55 0.22 25);
+    --status-comm-loss: oklch(0.50 0.05 260);
+  }
 }

+@media (prefers-reduced-motion: reduce) {
+  *, *::before, *::after {
+    animation-duration: 0.01ms !important;
+    animation-iteration-count: 1 !important;
+    transition-duration: 0.01ms !important;
+  }
+  .galaxy-container,
+  [class*="ambilight"],
+  [class*="aurora"] {
+    display: none !important;
+  }
+}
```

P0 子集 < 50 行，0 风险，可单独提交。
