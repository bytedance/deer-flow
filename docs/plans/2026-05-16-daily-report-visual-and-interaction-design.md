# 日报功能视觉与交互设计规范

> 日期：2026-05-16
> 状态：设计完成 — 报告内容采用纯文本+图片方案
> 关联 Agent：`ai-report--daily`
> 关联模块：GenUI 表单交互、Markdown 渲染管线、export_report.py

---

## 1. 产品上下文

- **产品**：DeerFlow — 企业级 AI 超级代理平台
- **目标用户**：企业运维/管理人员，查看设备运行日报，做出运营决策
- **日报形态**：AI 生成的叙事型数据报告。报告主体是一份 **Markdown 文本文档**，图表以 **内嵌图片（SVG/PNG）** 形式出现在文档中。交互表单用于收集参数，但报告内容本身是传统的"阅读型文档"，不是仪表盘式的 UI 组件拼接
- **交互模式**：4 轮渐进式表单（GenUI form block）→ 数据查询 → 生成统一 Markdown 文档（含图表图片）→ 导出下载

---

## 2. 核心架构决策

### 报告内容：文本 + 图片，不是 Block

```
┌──────────────────────────────────────────────────────────────┐
│  交互层（GenUI form block）                                    │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Round 1: form(daily-report-scope)                      │  │
│  │  Round 1.5: form(daily-report-equipment)                │  │
│  │  Round 2: form(daily-report-confirm)                    │  │
│  └────────────────────────────────────────────────────────┘  │
│                          ↓ 提交参数                            │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  后端：query_daily.py → daily_kpi.py                    │  │
│  │  → 图表渲染为 SVG → 组装 Markdown 文档                    │  │
│  └────────────────────────────────────────────────────────┘  │
│                          ↓                                    │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  报告层（纯 Markdown 文档）                               │  │
│  │                                                          │  │
│  │  # 设备运行日报                                           │  │
│  │  - 日期：2026-05-16                                       │  │
│  │  - 设备：共 238 台                                        │  │
│  │                                                          │  │
│  │  ## 概览                                                  │  │
│  │  整体运行平稳，运行率 96.8%...                              │  │
│  │                                                          │  │
│  │  ## KPI 指标                                              │  │
│  │  | 指标 | 当前 | 上一周期 | 变化 |                        │  │
│  │  |------|------|----------|------|                        │  │
│  │  | 运行率 | 96.8% | 95.6% | ↑ 1.2% |                     │  │
│  │                                                          │  │
│  │  ## 运行趋势                                              │  │
│  │  ![趋势图](data:image/svg+xml;base64,...)   ← 内嵌 SVG 图  │  │
│  │                                                          │  │
│  │  ## 异常事件                                              │  │
│  │  ...表格...                                               │  │
│  │                                                          │  │
│  │  ## 建议                                                  │  │
│  │  - 关注 SE-042 腐蚀速率异常                                │  │
│  └────────────────────────────────────────────────────────┘  │
│                          ↓                                    │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  导出层（GenUI form block）                               │  │
│  │  form(daily-report-export) → export_report.py           │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

### 与旧方案的本质区别

| | 旧方案（Block 组件拼装） | 新方案（文本文档） |
|---|---|---|
| 报告结构 | 5+ 个独立 GenUI Block：card×N + echart + table + markdown | 1 个 MarkdownBlock，内嵌表格和图片 |
| 图表渲染 | 前端 ECharts 实例（echarts-for-react） | 后端 Python 生成 SVG，内嵌 Markdown |
| 数据卡片 | CardBlock UI 组件 | Markdown 表格行 |
| 数据表格 | TableBlock UI 组件 | Markdown 表格 |
| 编辑能力 | 需要对每种 Block 分别实现编辑 | 统一 Markdown 编辑（P3 阶段） |
| 导出一致性 | 聊天界面与导出文件是两套渲染路径 | 同一份 Markdown 内容，聊天界面直展 + 导出直写 |
| 历史恢复 | 需要恢复多个 Block（含 ECharts option） | 只需恢复一份 Markdown 文本 |
| 前端复杂度 | CardBlock + EChartBlock + TableBlock + MarkdownBlock 都要维护 | 只需 MarkdownBlock 渲染 |

---

## 3. 配色方案

### 3.1 暗色模式（默认）

| 角色 | 色值 | CSS 变量 | 用途 |
|------|------|----------|------|
| 页面背景 | `#0D0F14` | `--background` | 最底层背景，比纯黑柔和 |
| 区块表面 | `#161820` | `--card` | 表单/报告容器 |
| 悬浮表面 | `#1C1F28` | `--card-hover` | hover 状态 |
| 边框 | `#2A2D36` | `--border` | 分割线、输入框边框 |
| 主强调色 | `#FF6B35` | `--primary` | 链接、CTA 按钮 |
| 次要强调 | `#4ECDC4` | `--secondary` | 图表辅助色 |
| 文字-主 | `#E8ECF1` | `--foreground` | 正文、标题 |
| 文字-次 | `#8B919B` | `--muted-foreground` | 辅助信息、标签 |
| 成功 | `#2ECC71` | `--success` | 正向指标、↑ 趋势 |
| 警告 | `#F39C12` | `--warning` | 异常提示 |
| 错误 | `#E74C3C` | `--danger` | 严重告警、↓ 趋势 |
| 信息 | `#3498DB` | `--info` | 中性提示 |

### 3.2 浅色模式

| 角色 | 色值 | 变化说明 |
|------|------|----------|
| 页面背景 | `#F5F6F8` | 暖灰白 |
| 区块表面 | `#FFFFFF` | 纯白容器 |
| 边框 | `#E2E4E9` | 浅灰 |
| 主强调色 | `#E55C2B` | 暖橙加深保证白底对比度 |
| 文字-主 | `#1A1D24` | 深色正文 |
| 文字-次 | `#6B7280` | 灰色辅助 |

### 3.3 图表色板

用于 SVG 图表中的多系列折线/柱状图。按顺序分配：

```
#FF6B35  #4ECDC4  #3498DB  #F39C12
#2ECC71  #9B59B6  #E74C3C  #1ABC9C
```

### 3.4 Markdown 中的语义色

日报 Markdown 中的数值通过 CSS 类或行内样式表达语义色。前端 MarkdownBlock 渲染时识别以下模式：

| Markdown 写法 | 渲染效果 |
|-------------|---------|
| `↑ 1.2%` | 绿色（`--success`） |
| `↓ 0.5%` | 红色（`--danger`） |
| `→ 0.0%` | 灰色（`--muted-foreground`） |
| 告警数 0 | 绿色 |
| 告警数 > 0 | 红色 |

---

## 4. 字体方案

| 角色 | 字体 | CSS | 理由 |
|------|------|-----|------|
| 标题/展示 | Satoshi | `"Satoshi", sans-serif` | 现代几何无衬线，在数据工具中罕见，有辨识度 |
| 正文 | Source Sans 3 | `"Source Sans 3", sans-serif` | 屏幕长文阅读优化，开源 |
| 数据/表格 | DM Sans | `"DM Sans", sans-serif` | 支持 `tabular-nums`，表格列对齐精准 |
| 代码/数值 | JetBrains Mono | `"JetBrains Mono", monospace` | 等宽 + 连字 |
| 中文回退 | Noto Sans SC | `"Noto Sans SC", sans-serif` | 与 Source Sans 3 搭配 |

### 排版层级（Markdown 文档内）

| 层级 | 字号 | 字重 | 行高 | Markdown 映射 |
|------|------|------|------|-------------|
| H1 | 24px | 700 | 1.3 | `# 日报标题` |
| H2 | 18px | 600 | 1.4 | `## 区域标题` |
| H3 | 15px | 600 | 1.4 | `### 子标题` |
| Body | 14px | 400 | 1.6 | 正文段落 |
| Table-Cell | 12px | 400 | 1.5 | 表格单元格 |
| Caption | 11px | 500 | 1.4 | 图表题注 |

### 字体加载

```html
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:opsz@9..40&family=JetBrains+Mono&family=Noto+Sans+SC&family=Source+Sans+3&display=swap" rel="stylesheet">
```

Satoshi 从 Bunny CDN 自托管（Google Fonts 未收录）。

---

## 5. 间距系统

基准：8px

| Token | 值 | 用途 |
|-------|-----|------|
| `space-2xs` | 4px | 表格单元格内边距 |
| `space-xs` | 8px | 表单字段间距 |
| `space-sm` | 12px | 表单容器内边距 |
| `space-md` | 16px | 报告容器内边距、Markdown 段落间距 |
| `space-lg` | 24px | Markdown H2 上边距、表单之间 |
| `space-xl` | 32px | Markdown H1 上边距 |
| `space-2xl` | 48px | 报告大区块间距 |

---

## 6. 布局策略

**方式**：编辑叙事（Editorial）

报告内容以**阅读体验**为中心，完全走文档排版路线：

- 报告容器：最大宽度 800px，水平居中
- Markdown 正文：舒适阅读宽度 ~720px
- 内嵌表格：全宽 800px，自适应列宽
- 内嵌图表（SVG）：全宽 760px，居中
- 表单容器：最大宽度 560px，居中（与报告宽度区分）

### 页面布局

```
┌──────────────────────────────────────────────────────────┐
│                     [导航栏/Header]                        │
├──────────────────────────────────────────────────────────┤
│                                                            │
│   ┌──────────────────────────────────────────────┐       │
│   │  Round 1: form(daily-report-scope)            │       │  ← 560px 居中
│   └──────────────────────────────────────────────┘       │
│                                                            │
│   ┌──────────────────────────────────────────────┐       │
│   │  Round 1.5: form(daily-report-equipment)      │       │  ← 720px（多选需空间）
│   └──────────────────────────────────────────────┘       │
│                                                            │
│   ┌──────────────────────────────────────────────┐       │
│   │  Round 2: form(daily-report-confirm)          │       │  ← 560px 居中
│   └──────────────────────────────────────────────┘       │
│                                                            │
│   ═══════════════ 日报文档 ════════════════              │
│                                                            │
│   ┌──────────────────────────────────────────────┐       │
│   │                                              │       │
│   │  # 静设备运行日报                             │       │  ← 800px 居中
│   │                                              │       │
│   │  - 日期：2026-05-16                           │       │
│   │  - 设备：共 238 台                            │       │
│   │                                              │       │
│   │  ## 概览                                      │       │
│   │  整体运行平稳，运行率达 96.8%，较前一日...       │       │
│   │                                              │       │
│   │  ## KPI 指标                                  │       │
│   │  | 指标 | 当前 | 上一周期 | 变化 |            │       │  ← Markdown 表格
│   │  |------|------|----------|------|            │       │
│   │  | 运行率 | 96.8% | 95.6% | ↑ 1.2% |         │       │
│   │                                              │       │
│   │  ## 运行趋势                                  │       │
│   │  ┌──────────────────────────────────────┐    │       │
│   │  │          SVG 趋势图                    │    │       │  ← 内嵌 760px SVG
│   │  └──────────────────────────────────────┘    │       │
│   │                                              │       │
│   │  ## 异常事件                                  │       │
│   │  | 时间 | 设备 | 级别 | 描述 |               │       │
│   │  |------|------|------|------|               │       │
│   │                                              │       │
│   │  ## 建议                                      │       │
│   │  - 重点关注 SE-042 腐蚀速率异常                │       │
│   │                                              │       │
│   └──────────────────────────────────────────────┘       │
│                                                            │
│   ┌──────────────────────────────────────────────┐       │
│   │  Export: form(daily-report-export)            │       │  ← 560px 居中
│   └──────────────────────────────────────────────┘       │
│                                                            │
└──────────────────────────────────────────────────────────┘
```

### 响应式断点

| 断点 | 宽度 | 报告容器宽度 | 表单宽度 |
|------|------|------------|----------|
| Mobile | < 640px | 100% - 16px | 100% |
| Tablet | 640-1024px | 90% | 80% |
| Desktop | ≥ 1024px | 800px | 560px |

---

## 7. 动效策略

**方式**：Minimal-Functional — 日报是文档，不搞花哨动效。

| 动效 | 时长 | 触发场景 |
|------|------|----------|
| MarkdownBlock 淡入 | 150ms | 报告文档首次渲染完成 |
| 表单提交按钮 loading | 250ms | 提交等待中 |
| 表单字段 focus 过渡 | 100ms | 边框色切换 |
| hover 反馈 | 100ms | 链接、按钮悬停 |

---

## 8. 交互设计

### 8.1 整体交互流程

```
用户进入日报
    │
    ▼
┌─────────────────────────────────────┐
│  Round 1: form(daily-report-scope)   │  GenUI form block
│  · 日报日期 (date picker)             │
│  · 设备类型 (select)                  │
│  · 对比基准 (select)                  │
│  [下一步 →]                           │
└─────────────────────────────────────┘
    │ 提交
    ▼
┌─────────────────────────────────────┐
│  Round 1.5: form(daily-report-       │  GenUI form block
│              equipment)              │
│  · 设备多选 (multi-select, 分组)      │
│  [下一步 →]                           │
└─────────────────────────────────────┘
    │ 提交
    ▼
┌─────────────────────────────────────┐
│  Round 2: form(daily-report-confirm) │  GenUI form block
│  · KPI 指标 (checkbox 列表)           │
│  [生成日报 →]                         │
└─────────────────────────────────────┘
    │ 提交 → Agent 查询数据 → 生成 Markdown
    ▼
┌─────────────────────────────────────┐
│  日报文档 (单个 MarkdownBlock)         │
│                                      │
│  # 设备运行日报                       │
│  - 日期 / 设备 / 对比                  │
│  ## 概览                              │
│  ## KPI 指标（Markdown 表格）          │
│  ## 运行趋势（内嵌 SVG 图片）           │
│  ## 异常事件（Markdown 表格）           │
│  ## 建议                              │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│  Export: form(daily-report-export)   │  GenUI form block
│  · 导出格式 (select: md/pdf)          │
│  [导出 →]                             │
└─────────────────────────────────────┘
    │ 提交 → export_report.py
    ▼
  ┌──────────────────────────┐
  │  📄 下载 daily_report.md  │  Markdown 链接
  └──────────────────────────┘
```

### 8.2 表单组件交互

表单（Round 1 / 1.5 / 2 / Export）仍然使用 GenUI `form` block。交互状态和行为不变。

#### 字段状态机

```
idle → focused → (valid | invalid) → submitted/readonly
                   ↓
                disabled (历史会话 / 已提交)

视觉表现：
  idle:     边框 var(--border), 背景 var(--card)
  focused:  边框 var(--primary), box-shadow 0 0 0 2px var(--primary)/20%
  invalid:  边框 var(--danger), box-shadow 0 0 0 2px var(--danger)/20%
            下方显示红色错误提示
  disabled: opacity 0.5, cursor: not-allowed
  readonly: 纯文本展示（无输入框外观）
  submitted: display: none
```

#### multi-select 交互

```
┌──────────────────────────────────────────────┐
│  🔍 搜索设备...                               │
├──────────────────────────────────────────────┤
│  ☑ 全选 (238)                                │
├──────────────────────────────────────────────┤
│  ▼ A区 (45)              [全选] [全不选]      │
│    ☑ SE-001  换热器-001                       │
│    ☑ SE-002  冷却器-002                       │
│    ☐ SE-003  分离器-003                       │
│  ▶ B区 (32)                                  │
├──────────────────────────────────────────────┤
│  已选：235 / 238                              │
└──────────────────────────────────────────────┘

特性：虚拟滚动（>500 条），分组折叠，搜索匹配，全选/全不选
```

#### 用户选择汇总

| 轮次 | callback_id | 选择项 | 字段类型 | 默认值 |
|------|-------------|--------|---------|--------|
| R1 | daily-report-scope | 日报日期 | date | — |
| R1 | daily-report-scope | 设备类型（全部/静设备/旋转机组/机泵/往复机组） | select | all |
| R1 | daily-report-scope | 对比基准（前一日/上周同日/不对比） | select | previous_day |
| R1.5 | daily-report-equipment | 设备列表 | multi-select (分组) | 全选 |
| R2 | daily-report-confirm | KPI 指标 | checkbox list | 全选 |
| Export | daily-report-export | 导出格式（md/pdf） | select | md |

### 8.3 报告文档状态

报告主体是一个 MarkdownBlock，有以下状态：

| 状态 | 前端表现 |
|------|---------|
| **加载中** | Skeleton 占位（高度约 600px 灰色脉冲块） |
| **渲染完成** | Markdown 文档正常显示，含表格和 SVG 图片 |
| **渲染失败** | 错误信息 + "重新生成"按钮（调用 Agent 重新生成） |
| **历史查看** | 正常显示，导出表单保持可用（`functional_interaction=true`） |
| **空数据** | Markdown 中对应区域显示 "该查询条件下无数据" |

### 8.4 图片交互

日报中的图片分为两类：

**A. 内嵌 SVG（默认方案）**

图表通过 data URI 直接嵌入 Markdown：

```markdown
## 运行趋势

<img src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0i..." alt="24h 运行率趋势" width="760">
```

- 图片与报告文本共存于同一个 MarkdownBlock
- 无需额外 HTTP 请求
- 导出时 SVG 直接写入 md 文件
- 缺点：SVG 体积大时分段加载略慢

**B. Artifact 引用（大图方案，>50KB）**

当 SVG 超过 50KB 时，走 artifact 文件路径：

```markdown
## 运行趋势

![24h 运行率趋势](/api/threads/{thread_id}/artifacts/outputs/trend_chart.svg)
```

- 前端 Markdown 渲染时自动处理 `/api/threads/...` 路径的图片加载
- 导出时脚本从 outputs 目录读取文件嵌入

### 8.5 导出流程

```
┌─────────────────────────────────┐
│  导出日报                         │
│  支持 Markdown 和 PDF 导出        │
│                                  │
│  导出格式                        │
│  ┌──────────────────────────┐   │
│  │  Markdown           ▼ │   │
│  └──────────────────────────┘   │
│                                  │
│  [导出 →]                        │
└─────────────────────────────────┘

提交后：
  1. 按钮 → "导出中..." + 旋转图标
  2. 后端调用 export_report.py
     - md 格式：写 Markdown 文本（含 SVG 内嵌）
     - pdf 格式：HTML→PDF via weasyprint
  3. present_files 触发
  4. 下方渲染下载链接 Markdown

错误状态：
  - weasyprint 未安装 → "PDF 导出需要 weasyprint，建议使用 Markdown 格式"
  - 脚本返回 error → 显示错误原因
```

### 8.6 历史会话查看

```
表单 Block：
  - 已提交的 form：隐藏
  - 未提交的 form：readonly 模式
  - functional_interaction=true 的导出表单：保持可用

报告 MarkdownBlock：
  - 正常显示（文档是静态内容，无交互状态变化）
  - 图片正常渲染
```

### 8.7 空状态 / 无数据

| 场景 | 报告中的展现 |
|------|------------|
| 无异常事件 | Markdown 文字："今日无异常事件。" |
| 无选中设备 | 校验拦截："请至少选择一台设备" |
| 无选中 KPI | 校验拦截："请至少选择一个 KPI 指标" |
| 脚本返回空数据 | Markdown 文字："该查询条件下无数据，请调整参数后重试" |
| 脚本返回错误 | Markdown 文字：展示 error 字段内容 |

### 8.8 键盘与无障碍

| 场景 | 行为 |
|------|------|
| Tab 导航 | 表单字段按 DOM 顺序聚焦 |
| Enter 提交 | 表单内 Enter 触发提交（textarea 除外） |
| 必填标记 | 红色 * 号 + aria-required="true" |
| 错误关联 | aria-describedby 关联错误信息 |
| 表单语义 | role="region" + aria-label |
| 色盲友好 | 趋势箭头上色同时有 ↑↓→ 方向符 |
| 图片 alt | 所有图表图片有描述性 alt 文本 |

---

## 9. 组件设计规范

### 9.1 涉及的 GenUI 组件

| 组件 | 用途 | 是否保留 |
|------|------|----------|
| **FormBlock** | 参数收集表单（Round 1/1.5/2/Export） | ✅ 保留 |
| **MarkdownBlock** | 承载完整日报文档 | ✅ 保留 + 强化 |
| CardBlock | — | ❌ 报告不再使用 |
| EChartBlock | — | ❌ 报告不再使用（图表改为后端 SVG） |
| TableBlock | — | ❌ 报告不再使用（表格改为 Markdown 表格） |

### 9.2 MarkdownBlock 强化

日报 MarkdownBlock 需要支持以下能力（当前已部分支持）：

| 能力 | 当前状态 | 日报需求 |
|------|---------|---------|
| Markdown 渲染 | ✅ streamdown 插件 | 保持一致 |
| 内嵌 HTML `<img>` | ✅ 需放行 data: URI | SVG data URI 图片 |
| 远程图片加载 | ✅ 需放行 `/api/threads/*` 路径 | artifact 大图 |
| Markdown 表格 | ✅ GFM 表格 | KPI 表、异常表 |
| 代码块 | ✅ | 不使用 |
| 引用块 | ✅ | 数据来源引用 |

**关键改动**：

1. **data: URI 图片放行**：MarkdownBlock 需要渲染 `<img src="data:image/svg+xml;base64,...">` 而不被 sanitize 过滤
2. **artifact 路径图片放行**：`<img src="/api/threads/{id}/artifacts/...">` 的 src 需要通过安全校验
3. **最大阅读宽度**：报告容器 `max-w-[800px]`，正文段落 `max-w-[720px]`
4. **图片最大宽度**：`max-w-[760px]`，居中

### 9.3 FormBlock 视觉升级

保持现有交互逻辑，视觉层面对齐设计规范：

- 容器背景 `var(--card)`
- 标题 18px / 600 字重
- 输入框 36px 高，圆角 4px
- 提交按钮：`var(--primary)` 背景，40px 高
- 错误文字：`var(--danger)` 色，12px

### 9.4 图表后端渲染方案

图表在**后端沙箱中**由 Python 渲染为 SVG，通过 `trend_chart_to_svg()` 函数（已存在于 `export_report.py`）完成：

```
daily_kpi.json (含 trend_chart ECharts option)
    │
    ▼
trend_chart_to_svg(trend_chart)
    │  解析 ECharts option → 生成纯 SVG 字符串
    ▼
render_markdown(payload)
    │  将 SVG 以 base64 data URI 嵌入 Markdown
    ▼
render_ui(component="markdown", content=full_report_md)
    │  一个 MarkdownBlock 包含所有内容
    ▼
前端 MarkdownBlock 渲染
```

存量代码 `export_report.py` 已有完整的 `trend_chart_to_svg()` 和 `render_markdown()`，可直接复用。

---

## 10. 后端 SOUL.md 改造要点

当前 SOUL.md 中报告渲染部分使用多个 `render_ui` 调用（card×N、echart、table、markdown）。改造后变为：

**改造前**（当前）：
```python
# Round 2 回调中
render_ui(component="card", ...)    # 概览卡片
render_ui(component="card", ...)    # KPI 卡片 × N
render_ui(component="echart", ...)  # 趋势图
render_ui(component="table", ...)   # 异常排行
render_ui(component="table", ...)   # 告警列表
render_ui(component="markdown", ...) # 总结
render_ui(component="form", ...)    # 导出表单
```

**改造后**（新方案）：
```python
# Round 2 回调中
# 1. 调用 daily_kpi.py 得到 daily_kpi.json
# 2. 调用 export_report.py:render_markdown(payload) 生成完整 Markdown
# 3. 一次 render_ui 输出整个日报文档
render_ui(component="markdown", content=report_markdown)
# 4. 渲染导出表单
render_ui(component="form", ..., functional_interaction=True)
```

图表 SVG 生成由 `export_report.py` 的 `trend_chart_to_svg()` 在后端完成，前端不需要 ECharts 实例。

---

## 11. 与功能改造计划的衔接

| 功能改造项 | 旧方案影响 | 新方案影响 |
|-----------|----------|----------|
| P0: Block sequence 排序 | 需要 5+ Block 排序 | **简化**：报告只有 1 个 MarkdownBlock + 1 个 FormBlock，排序压力大减 |
| P1: TTL 延长至 24h | 需要延长 5+ Block 的 TTL | **简化**：只需保持 1 个 MarkdownBlock 内容 |
| P2: functional_interaction | 导出表单需标记 | **不变**：导出表单仍需 `functional_interaction=true` |
| P2: ECharts Artifact 引用 | 需要 EChartBlock 处理异步加载 | **简化**：大 SVG 才走 artifact，优先 data URI 内嵌 |
| P2: 图表截图双保险 | 需要前端 ECharts 截图 | **不再需要**：图表是后端 SVG，导出时直接写入，无截图问题 |
| P3: 内容编辑能力 | 需要分别编辑 Card/Table/Markdown | **简化**：只需编辑一份 Markdown 文本 |

---

## 12. 参考

| 模块 | 文件 |
|------|------|
| 日报 SOUL | [agents/builtin/ai-report--daily/SOUL.md](../../agents/builtin/ai-report--daily/SOUL.md) |
| 导出脚本（含 SVG 渲染 + Markdown 生成） | [skills/custom/data-analyst/scripts/export_report.py](../../skills/custom/data-analyst/scripts/export_report.py) |
| KPI 计算脚本 | [skills/custom/data-analyst/scripts/daily_kpi.py](../../skills/custom/data-analyst/scripts/daily_kpi.py) |
| FormBlock 组件 | [frontend/src/components/genui/FormBlock.tsx](../../frontend/src/components/genui/FormBlock.tsx) |
| MarkdownBlock 组件 | [frontend/src/components/genui/MarkdownBlock.tsx](../../frontend/src/components/genui/MarkdownBlock.tsx) |
| 功能改造计划 | [docs/plans/2026-05-15-daily-report-render-evaluation-and-fix.md](./2026-05-15-daily-report-render-evaluation-and-fix.md) |
| 竞品参考 | Grafana Saga Design System、Datadog Dashboards、Metabase BI |
