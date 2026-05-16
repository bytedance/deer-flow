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
| **编辑中** | Markdown 渲染视图切换为源码编辑视图（textarea），显示原始 Markdown 文本 |
| **空数据** | Markdown 中对应区域显示 "该查询条件下无数据" |

### 8.4 图片交互

日报中的图片分为两类。**关键约束**：前端 [sanitizer.ts](../../frontend/src/core/genui/sanitizer.ts) 对所有 string 类型 props 执行 `DOMPurify.sanitize(value, { ALLOWED_TAGS: [], ALLOWED_ATTR: [] })`，会剥离所有 HTML 标签。因此图片不能使用 HTML `<img>` 标签，必须使用 **Markdown 原生图片语法** `![alt](url)`，由 remark/rehype 在渲染层直接转为 `<img>` 元素，不经过 DOMPurify。

**A. 内嵌 SVG（默认方案，≤50KB）**

图表通过 Markdown 图片语法 + base64 data URI 嵌入：

```markdown
## 运行趋势

![24h 运行率趋势](data:image/svg+xml;base64,PHN2ZyB4bWxucz0i...)
```

- `export_report.py` 的 `render_markdown()` 需要将 `<img src="data:...">` 改为 `![](data:...)` 格式
- 图片与报告文本共存于同一个 MarkdownBlock，无需额外 HTTP 请求
- 导出时 SVG 数据直接写入 md 文件（`<img>` 或 `![]()` 均可）
- streamdown 管线已配置 `rehype-raw`（[plugins.ts:14](../../frontend/src/core/streamdown/plugins.ts#L14)），渲染层支持 raw HTML

**B. Artifact 引用（大图方案，>50KB）**

当 SVG base64 超过 50KB 时，后端将 SVG 写入 `/mnt/user-data/outputs/`，Markdown 中引用 artifact 路径：

```markdown
## 运行趋势

![24h 运行率趋势](/api/threads/{thread_id}/artifacts/outputs/trend_chart.svg)
```

- 前端 Markdown 渲染时，`<img>` 的 `src` 指向 artifact 端点，浏览器自动发起请求
- 前端 `sanitizeValue` 不会剥离 Markdown 图片语法的 URL 部分（URL 不包含 HTML 标签）
- 导出时脚本从 outputs 目录读取文件嵌入
- 阈值判断在后端 `render_markdown()` 中完成：`len(svg_str) * 1.37 ≈ base64_size`，>50KB 时走 artifact

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

### 8.9 Markdown 内容编辑

日报生成后，用户可直接在聊天界面中编辑 Markdown 源码，修改报告内容后再导出。

#### 编辑入口

```
┌──────────────────────────────────────────────┐
│  日报文档                        [编辑] [导出] │  ← 工具栏常驻
├──────────────────────────────────────────────┤
│                                              │
│  # 设备运行日报                               │
│  ...                                         │
│                                              │
└──────────────────────────────────────────────┘
```

- 报告容器右上角显示 **"编辑"按钮**（icon + 文字，`--muted-foreground` 色）
- 点击进入编辑模式

#### 编辑模式

```
┌──────────────────────────────────────────────┐
│  编辑日报                        [取消] [保存] │  ← 操作栏
├──────────────────────────────────────────────┤
│  ┌──────────────────────────────────────────┐│
│  │ # 设备运行日报                             ││
│  │                                          ││
│  │ - 日期：2026-05-16                        ││
│  │ - 设备：共 238 台                          ││
│  │                                          ││
│  │ ## 概览                                   ││
│  │ 整体运行平稳...                             ││
│  │                                          ││
│  │ ## KPI 指标                               ││  ← textarea，等宽字体
│  │ | 指标 | 当前 | 上一周期 | 变化 |           ││
│  │ |------|------|----------|------|         ││
│  │ | 运行率 | 96.8% | 95.6% | ↑ 1.2% |      ││
│  │                                          ││
│  │ ## 运行趋势                                ││
│  │ ![趋势图](data:image/svg+xml;base64,...)   ││  ← SVG 以 base64 文本呈现
│  │                                          ││
│  └──────────────────────────────────────────┘│
└──────────────────────────────────────────────┘
```

**交互规则**：

| 操作 | 行为 |
|------|------|
| 进入编辑 | Markdown 渲染视图 → textarea 源码视图，textarea 自动获取焦点 |
| textarea 样式 | 等宽字体（JetBrains Mono），14px，行高 1.6，min-height 400px，全宽 |
| 编辑内容 | 自由修改 Markdown 文本，包括表格数据、文字描述、图片 base64 |
| 保存 | 更新 `block.props.content`→ 触发 MarkdownBlock 重新渲染 → 回到渲染视图。保存成功后显示短暂 toast "已保存" |
| 取消 | 放弃修改，直接回到渲染视图。如有未保存修改，弹出确认："放弃未保存的修改？" |
| 导出 | 始终使用最新的 `block.props.content`（编辑后的版本） |

**状态转换**：

```
渲染视图 ──[点击编辑]──→ 编辑视图 ──[保存]──→ 渲染视图（新内容）
                ←──[取消]──
```

**约束**：

- 编辑仅影响前端 block 状态（Zustand store），不触发后端 Agent 重新生成
- 编辑后的内容随 block 持久化（历史恢复时保留修改）
- 图片 base64 data URI 在 textarea 中完整显示（不可见但可编辑），用户可替换或删除
- PDF 导出时使用编辑后的 Markdown 内容

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

日报 MarkdownBlock 需要支持以下能力：

| 能力 | 当前状态 | 日报需求 | 改造方式 |
|------|---------|---------|---------|
| Markdown 渲染 | ✅ streamdown 插件 | 保持一致 | 无需改动 |
| Markdown 图片 `![](url)` | ✅ remark-gfm 原生支持 | SVG data URI 图片 | `![alt](data:image/svg+xml;base64,...)` — 不经过 HTML sanitizer |
| 远程图片加载 | ⚠️ 需验证 | artifact 大图 | `![alt](/api/threads/{id}/artifacts/...)` — 需验证 streamdown 对该路径的处理 |
| Markdown 表格 | ✅ GFM 表格 | KPI 表、异常表 | 无需改动 |
| HTML `<img>` 标签 | ❌ sanitizer 剥离 | 不可用 | 不得使用 `<img>` 标签，统一走 Markdown 图片语法 |
| Markdown 源码编辑 | ❌ 当前仅渲染 | 用户直接修改报告内容 | 新增编辑模式：渲染视图 ↔ textarea 源码视图切换 |

**Sanitizer 绕过机制（关键）**：

当前 [sanitizer.ts:39-46](../../frontend/src/core/genui/sanitizer.ts#L39-L46) 对所有 string props 执行：
```typescript
DOMPurify.sanitize(value, { ALLOWED_TAGS: [], ALLOWED_ATTR: [] })
```

这会剥离 `markdown.content` 中的 `<img src="...">` 等 HTML 标签。**绕过方式**：使用 Markdown 原生图片语法 `![alt](data:image/svg+xml;base64,...)` — 这是纯文本，不包含 HTML 标签，由 remark/rehype 在渲染层转为 `<img>` 元素。streamdown 管线已配置 `rehype-raw`（[plugins.ts:14](../../frontend/src/core/streamdown/plugins.ts#L14)），渲染层支持 raw HTML。

**注意**：如果将来需要更宽松的 sanitizer（例如允许 `<img>` 标签包含 `src="data:"` 属性），可在 `sanitizeValue` 中对 `markdown` 组件的 `content` 属性做特殊处理。但当前 Markdown 图片语法方案已足够，优先使用。

**前端需改造的文件**：

| 文件 | 改动 | 原因 |
|------|------|------|
| `sanitizer.ts` | 无需改动 | Markdown 图片语法不经过 DOMPurify |
| `MarkdownBlock.tsx` | 添加报告容器样式类 | `max-w-[800px]` 等排版约束 |
| `export_report.py` | `render_markdown()` 中 `<img>` → `![]()` | 适配 sanitizer 约束 |

**SVG 暗色模式适配**：

当前 `trend_chart_to_svg()`（[export_report.py:63](../../skills/custom/data-analyst/scripts/export_report.py#L63)）硬编码浅色背景 `#fff` 和深色文字 `#333`。在日报页面的暗色模式下（`--background: #0D0F14`），白色 SVG 块会非常刺眼。需要在 `render_markdown()` 被调用时传入主题参数，使 SVG 配色适配：

| SVG 元素 | 暗色模式值 | 浅色模式值 |
|---------|----------|----------|
| 背景 | `#161820`（`var(--card)`）| `#FFFFFF` |
| 文字 | `#E8ECF1`（`var(--foreground)`）| `#1A1D24` |
| 网格线 | `#2A2D36`（`var(--border)`）| `#E2E4E9` |
| 坐标标签 | `#8B919B`（`var(--muted-foreground)`）| `#6B7280` |

由于 Agent 在沙箱中运行，无法直接读取前端主题。方案：
- 短期：SVG 使用透明背景 `fill="transparent"`，让报告容器背景透出（推荐）
- 长期：前端检测到 SVG 图片时，CSS 注入 `img[src*="svg"] { background: var(--card); }` 覆盖

**artifact 大图阈值判定**：

在 `export_report.py` 中增加阈值判断逻辑：

```python
_MAX_INLINE_SVG_BYTES = 50 * 1024  # 50KB

def _embed_chart_image(svg_str: str, alt: str, thread_id: str | None = None) -> str:
    """Return markdown image syntax for a chart SVG."""
    b64 = base64.b64encode(svg_str.encode("utf-8")).decode("ascii")
    data_uri = f"data:image/svg+xml;base64,{b64}"
    if len(data_uri) <= _MAX_INLINE_SVG_BYTES:
        return f"![{alt}]({data_uri})"
    # 大图：写文件 + artifact 引用
    if thread_id:
        out = _output_dir() / "trend_chart.svg"
        out.write_text(svg_str, encoding="utf-8")
        return f"![{alt}](/api/threads/{thread_id}/artifacts/outputs/trend_chart.svg)"
    # 无 thread_id 时仍走内嵌（导出场景）
    return f"![{alt}]({data_uri})"
```

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

## 10. 后端设计

> 本章覆盖后端所有改造点：Agent 交互流程、render_ui_tool 接口扩展、genui_persistence 生命周期、export_report.py 渲染管线、SSE 事件流、错误处理。

### 10.1 Agent 交互流程（后端视角）

日报 Agent 通过 4 轮表单交互收集参数，然后调用数据脚本生成统一 Markdown 报告。

```
用户进入日报 (thread 创建)
    │
    ▼
Agent Round 1: render_ui(component="form", callback_id="daily-report-scope", ...)
    │  收集: 日期、设备类型、对比基准
    │  GenUI 交互 → LangGraph interrupt → 等待用户提交
    │
    ▼
Agent Round 1.5: render_ui(component="form", callback_id="daily-report-equipment", ...)
    │  收集: 设备多选（分组）
    │  GenUI 交互 → LangGraph interrupt → 等待用户提交
    │
    ▼
Agent Round 2: render_ui(component="form", callback_id="daily-report-confirm", ...)
    │  收集: KPI 指标（checkbox）
    │  GenUI 交互 → LangGraph interrupt → 等待用户提交
    │
    ▼
Agent Round 2 回调:
    │  1. bash("python skills/custom/data-analyst/scripts/daily_kpi.py ...")
    │     → 输出 daily_kpi.json 到 /mnt/user-data/outputs/
    │
    │  2. bash("python skills/custom/data-analyst/scripts/export_report.py --format md")
    │     → render_markdown() 组装 Markdown（含 SVG 图表）
    │     或直接在 Agent 代码中 import 并调用 render_markdown()
    │
    │  3. render_ui(component="markdown", content=report_markdown)
    │     → 一个 MarkdownBlock 包含完整日报
    │
    │  4. render_ui(component="form", callback_id="daily-report-export",
    │              functional_interaction=True)
    │     → 导出表单（历史会话中保持可用）
    │
    ▼
Agent Export 回调:
    │  bash("python export_report.py --format {md|pdf}")
    │  → present_files() 触发下载
    ▼
  完成
```

**关键变化**（对比旧方案）：
- Round 2 回调从 7-10 次 `render_ui` 调用 → 2 次（1 markdown + 1 form）
- 图表渲染从"前端 ECharts"变为"后端生成 SVG 内嵌 Markdown"
- SOUL.md 中移除 card/echart/table 相关的 `render_ui` 指令

### 10.2 render_ui_tool 接口扩展

当前 [render_ui_tool.py:21-30](../../backend/packages/harness/deerflow/tools/builtins/render_ui_tool.py#L21-L30) 函数签名：

```python
def render_ui_tool(
    component: str,
    props: dict,
    interactive: bool = False,
    callback_id: str | None = None,
    callback_timeout_ms: int | None = None,
    parent_id: str | None = None,
    block_id: str | None = None,
    action: str = "create",
) -> str:
```

**新增参数**：

| 参数 | 类型 | 默认值 | 用途 |
|------|------|--------|------|
| `sequence` | `int \| None` | `None` | Block 排序序号，前端按此升序渲染 |
| `functional_interaction` | `bool` | `False` | 是否为功能性交互（历史会话中保持可用） |

**block 构造处改造**（[render_ui_tool.py:76-91](../../backend/packages/harness/deerflow/tools/builtins/render_ui_tool.py#L76-L91)）：

```python
block = {
    "schema_version": SCHEMA_VERSION,
    "type": "ui_block",
    "action": action,
    "block_id": resolved_block_id,
    "component": component,
    "props": props,
    "interactive": interactive,
}

if callback_id:
    block["callback_id"] = callback_id
if callback_timeout_ms is not None:
    block["callback_timeout_ms"] = callback_timeout_ms
if parent_id:
    block["parent_id"] = parent_id
# 新增字段
if sequence is not None:                         # ← 新增
    block["sequence"] = sequence                 # ← 新增
if functional_interaction:                       # ← 新增
    block["functional_interaction"] = True       # ← 新增
```

**StreamWriter 行为**：

render_ui_tool 通过 `get_stream_writer()(block)` 发出 SSE 自定义事件，前端 GenUIRenderer 接收后调用 `applyBlock()` 写入 Zustand store。`sequence` 字段被透传到前端，GenUIRenderer 在渲染前按 `sequence` 排序 blocks。

SSE 事件格式示例：

```json
{
  "schema_version": "1.0",
  "type": "ui_block",
  "action": "create",
  "block_id": "daily-report-markdown-001",
  "component": "markdown",
  "props": { "content": "# 设备运行日报\n...", "title": "设备运行日报" },
  "interactive": false,
  "sequence": 1
}
```

### 10.3 genui_persistence.py 改造

当前 [genui_persistence.py:11](../../backend/packages/harness/deerflow/agents/genui_persistence.py#L11) TTL 为 1 小时：

```python
_BLOCK_TTL_SECONDS = 3600  # ← 改为 86400（24 小时）
```

改动：一行常量修改，无其他逻辑变更。

**Block 生命周期**（新方案下）：

```
create (action="create")
  → persist_block() 写入内存
  → TTL = 86400s（24h）
  → 前端 applyBlock() 写入 Zustand store
  → 用户编辑（前端 store 更新，不经过后端）

历史恢复:
  → extract_blocks_from_messages() 从 ToolMessage 中解析 <!--ui_block:{json}-->
  → 或 get_persisted_blocks() 从内存中获取（TTL 内）
  → _fold_blocks() 合并 create/update/delete → 最终状态

删除 (action="delete"):
  → persist_block() 记录 delete 事件
  → _fold_blocks() 移除该 block
```

**interaction 注册**（[render_ui_tool.py:98-109](../../backend/packages/harness/deerflow/tools/builtins/render_ui_tool.py#L98-L109)）：

interaction 注册逻辑不变。`functional_interaction=true` 的 block 的 interaction 在历史恢复时不会被标记为 expired/readonly，前端据此保持交互可用。

### 10.4 export_report.py 渲染管线改造

改造集中在 `render_markdown()` 函数（[export_report.py:216](../../skills/custom/data-analyst/scripts/export_report.py#L216)），共 4 处改动：

#### 10.4.1 `<img>` → `![]()` 转换（P0，阻塞项）

当前使用 HTML 标签：

```python
# 旧（会被 sanitizer 剥离）
lines.append(f'<img src="data:image/svg+xml;base64,{b64}" alt="运行趋势图" width="760">')
```

改为 Markdown 原生图片语法：

```python
# 新（绕过 sanitizer）
lines.append(f'![运行趋势图](data:image/svg+xml;base64,{b64})')
```

涉及位置：
- [export_report.py:296](../../skills/custom/data-analyst/scripts/export_report.py#L296)：`_read_image_as_data_uri` 路径
- [export_report.py:306](../../skills/custom/data-analyst/scripts/export_report.py#L306)：趋势图直接 base64 路径
- [export_report.py:316](../../skills/custom/data-analyst/scripts/export_report.py#L316)：`chart_images=None` 趋势图路径

#### 10.4.2 `_embed_chart_image()` 新增（P1）

阈值判断：≤50KB 内嵌 base64，>50KB 写 artifact 文件并引用 URL。

```python
import base64
from pathlib import Path

_MAX_INLINE_SVG_BYTES = 50 * 1024  # 50KB


def _embed_chart_image(svg_str: str, alt: str, thread_id: str | None = None) -> str:
    """将 SVG 字符串转为 Markdown 图片语法，大图走 artifact 引用。"""
    b64 = base64.b64encode(svg_str.encode("utf-8")).decode("ascii")
    data_uri = f"data:image/svg+xml;base64,{b64}"
    if len(data_uri) <= _MAX_INLINE_SVG_BYTES:
        return f"![{alt}]({data_uri})"
    # 大图：写文件 + artifact 引用
    if thread_id:
        out = _output_dir() / f"chart_{abs(hash(svg_str)) % 100000}.svg"
        out.write_text(svg_str, encoding="utf-8")
        return f"![{alt}](/api/threads/{thread_id}/artifacts/outputs/{out.name})"
    # 无 thread_id（导出场景）仍走内嵌
    return f"![{alt}]({data_uri})"
```

#### 10.4.3 SVG 暗色模式适配（P1）

`trend_chart_to_svg()`（[export_report.py:63](../../skills/custom/data-analyst/scripts/export_report.py#L63)）当前硬编码浅色配色：

```python
# 当前
parts.append(f'<rect width="{SVG_W}" height="{SVG_H}" fill="#fff"/>')
# ...
parts.append(f'font-family="SimSun,Noto Sans SC,sans-serif" fill="#333"
```

改造为接收可选主题参数，默认使用透明背景：

```python
def trend_chart_to_svg(chart: dict, theme: str = "light") -> str:
    """theme: 'light' | 'dark' | 'transparent'"""
    if theme == "dark":
        bg, fg, grid, muted = "#161820", "#E8ECF1", "#2A2D36", "#8B919B"
    elif theme == "transparent":
        bg, fg, grid, muted = "transparent", "currentColor", "#2A2D36", "#8B919B"
    else:
        bg, fg, grid, muted = "#fff", "#333", "#eee", "#666"

    parts.append(f'<rect width="{SVG_W}" height="{SVG_H}" fill="{bg}"/>')
    # ... 文字和网格使用 fg / grid / muted
```

**推荐短期方案**：`theme="transparent"` — SVG 背景透明，让前端 CSS `img[src*="svg"] { background: var(--card); }` 提供背景色，自适应主题切换。

#### 10.4.4 `render_markdown()` 签名扩展

```python
def render_markdown(
    payload: dict,
    chart_images: list[str] | None = None,
    thread_id: str | None = None,      # ← 新增：用于 artifact 路径
    theme: str = "transparent",         # ← 新增：SVG 主题
) -> str:
```

#### 10.4.5 render_ui_tool 中图表渲染的替代调用方式

Agent 在 SOUL.md 中不直接调用 `export_report.py` 的 CLI，而是通过 Python import 调用：

```python
# Agent 代码中（SOUL.md 指导）
from skills.custom.data_analyst.scripts.export_report import (
    render_markdown,
    trend_chart_to_svg,
    _embed_chart_image,
)
import json

# 1. 读取 daily_kpi.json
kpi_data = json.loads(read_file("/mnt/user-data/outputs/daily_kpi.json"))

# 2. 生成完整 Markdown
report_md = render_markdown(kpi_data, thread_id=thread_id, theme="transparent")

# 3. 输出到前端
render_ui(component="markdown", props={"content": report_md}, sequence=1)
render_ui(
    component="form",
    callback_id="daily-report-export",
    interactive=True,
    functional_interaction=True,
    sequence=2,
    props={
        "title": "导出日报",
        "fields": [
            {
                "name": "format",
                "type": "select",
                "label": "导出格式",
                "options": [
                    {"label": "Markdown (.md)", "value": "md"},
                    {"label": "PDF (.pdf)", "value": "pdf"},
                ],
                "default_value": "md",
            }
        ],
        "submit_label": "导出",
    },
)
```

### 10.5 SSE 事件流与前端对接

后端到前端的完整事件链路：

```
Agent render_ui_tool()
    │  block dict
    ▼
StreamWriter (LangGraph custom stream mode)
    │  SSE: event: custom, data: {"type": "ui_block", ...}
    ▼
LangGraph SDK (前端 getAPIClient())
    │  streamEvents()
    ▼
前端 GenUIRenderer
    │  applyBlock(block) → Zustand store
    │  sanitizeProps(component, props) → DOMPurify
    ▼
MarkdownBlock 组件
    │  MessageResponse + streamdownPlugins
    ▼
渲染输出
```

**关键节点说明**：

1. **StreamWriter**（[render_ui_tool.py:93-94](../../backend/packages/harness/deerflow/tools/builtins/render_ui_tool.py#L93-L94)）：`writer(block)` 将 block dict 作为自定义事件发出
2. **persist_block**（[render_ui_tool.py:96](../../backend/packages/harness/deerflow/tools/builtins/render_ui_tool.py#L96)）：同步写入内存，用于 TTL 内恢复
3. **interaction 注册**（[render_ui_tool.py:98-109](../../backend/packages/harness/deerflow/tools/builtins/render_ui_tool.py#L98-L109)）：仅对 `interactive=True` + `action="create"` 的 block 注册 interaction
4. **ToolMessage 标记**（[render_ui_tool.py:113](../../backend/packages/harness/deerflow/tools/builtins/render_ui_tool.py#L113)）：返回的字符串中包含 `<!--ui_block:{json}-->` 注释，用于 checkpoint 恢复时 `extract_blocks_from_messages()` 解析

### 10.6 后端错误处理

| 场景 | 错误来源 | 处理方式 |
|------|---------|---------|
| daily_kpi.py 执行失败 | bash tool 返回非零 | Agent 捕获 stderr，`render_ui(component="markdown", content="数据查询失败：{error}")` 展示错误 |
| daily_kpi.json 不存在 | read_file 返回 FileNotFoundError | Agent 调用 `render_ui` 展示 "数据文件未生成，请重试" |
| trend_chart_to_svg() 空数据 | 无 series / 无有效数据 | 返回空字符串 `""`，Markdown 中跳过趋势图章节 |
| SVG base64 超过阈值 | _embed_chart_image() | 自动降级为 artifact 文件引用 |
| export_report.py 执行失败 | bash tool / ImportError | Agent 捕获错误，展示具体原因（如 "PDF 导出需要 weasyprint"） |
| render_ui_tool 参数错误 | 参数校验 | 返回错误字符串，前端可展示（如 component 不在 ALLOWED_COMPONENTS 中） |
| persist_block 失败 | 线程锁异常 | 仅影响历史恢复，前端实时渲染不受影响（StreamWriter 已发出） |
| interaction 注册失败 | genui_middleware 异常 | 交互组件在历史会话中不可用，当前会话仍正常 |

**Agent 端错误处理模式**（SOUL.md 指导）：

```python
# 模板：SOUL.md 中指导 Agent 的错误处理
try:
    kpi_data = json.loads(read_file("/mnt/user-data/outputs/daily_kpi.json"))
except Exception as e:
    render_ui(
        component="markdown",
        props={"content": f"# 日报生成失败\n\n数据查询出错：{e}\n\n请检查参数后重试。"},
    )
    return

report_md = render_markdown(kpi_data, thread_id=thread_id, theme="transparent")
if not report_md.strip():
    render_ui(
        component="markdown",
        props={"content": "# 日报生成失败\n\n该查询条件下无数据，请调整参数后重试。"},
    )
    return

render_ui(component="markdown", props={"content": report_md}, sequence=1)
```

### 10.7 后端文件改动汇总

| 文件 | 改动项 | 行数 | 优先级 |
|------|--------|------|--------|
| `render_ui_tool.py` | 新增 `sequence` + `functional_interaction` 参数，透传至 block dict | ~15 行 | P0/P2 |
| `genui_persistence.py` | TTL `3600` → `86400` | 1 行 | P1 |
| `export_report.py` | `<img>` → `![]()` (3 处) | ~6 行 | P0 |
| `export_report.py` | 新增 `_embed_chart_image()` | ~25 行 | P1 |
| `export_report.py` | `trend_chart_to_svg()` 主题参数 | ~20 行 | P1 |
| `export_report.py` | `render_markdown()` 签名扩展 | ~5 行 | P1 |
| `SOUL.md` | 多 `render_ui` → 单 markdown + form | ~50 行 | P0 |

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

## 12. 架构评估与实施路径

> 本章基于对存量代码库的详细评估，分析设计规范落地的可行性、差距和风险，并规划实施阶段。

### 12.1 存量资产分析

以下存量模块可直接复用，无需新建：

| 资产 | 位置 | 复用方式 | 状态 |
|------|------|---------|------|
| `trend_chart_to_svg()` | [export_report.py#L63](../../skills/custom/data-analyst/scripts/export_report.py#L63) | 后端渲染 ECharts option → SVG 字符串 | ✅ 已就绪 |
| `render_markdown()` | [export_report.py](../../skills/custom/data-analyst/scripts/export_report.py) | 组装完整 Markdown 日报文档 | ⚠️ 需改 `<img>` → `![]()` |
| `render_html()` | [export_report.py](../../skills/custom/data-analyst/scripts/export_report.py) | Markdown → HTML 全文（PDF 导出用） | ✅ 已就绪 |
| `build_export_result()` / `write_report()` | [export_report.py](../../skills/custom/data-analyst/scripts/export_report.py) | 导出文件写入和结果构造 | ✅ 已就绪 |
| FormBlock 组件 | [frontend/src/components/genui/FormBlock.tsx](../../frontend/src/components/genui/FormBlock.tsx) | 4 轮表单交互（select / multi-select / checkbox / date） | ✅ 已就绪 |
| MarkdownBlock 组件 | [frontend/src/components/genui/MarkdownBlock.tsx](../../frontend/src/components/genui/MarkdownBlock.tsx) | 报告 Markdown 渲染容器 | ⚠️ 需添加排版样式 |
| streamdown 插件管线 | [frontend/src/core/streamdown/plugins.ts](../../frontend/src/core/streamdown/plugins.ts) | remark + rehype 渲染（已含 rehype-raw） | ✅ 已就绪 |
| GenUI block store | [frontend/src/core/genui/store.ts](../../frontend/src/core/genui/store.ts) | block 状态管理（create/update/delete） | ✅ 已就绪 |
| GenUI history recovery | [frontend/src/core/genui/history.ts](../../frontend/src/core/genui/history.ts) | 历史会话恢复 | ✅ 简化受益 |
| render_ui_tool | [backend/.../render_ui_tool.py](../../backend/packages/harness/deerflow/tools/builtins/render_ui_tool.py) | 创建/更新/删除 UI block | ⚠️ 需加 `sequence` + `functional_interaction` |
| daily_kpi.py | [skills/custom/data-analyst/scripts/daily_kpi.py](../../skills/custom/data-analyst/scripts/daily_kpi.py) | KPI 计算和趋势图数据 | ✅ 已就绪 |
| 4 轮表单 SOUL 流程 | [agents/builtin/ai-report--daily/SOUL.md](../../agents/builtin/ai-report--daily/SOUL.md) | 参数收集交互流程 | ✅ 已就绪 |

### 12.2 增量改造清单

需要新建或改造的内容：

| # | 改造项 | 位置 | 工作量 | 优先级 | 依赖 |
|---|--------|------|--------|--------|------|
| 1 | `render_markdown()` 中 `<img>` → `![]()` | export_report.py | ~10 行 | P0 | 无 |
| 2 | 添加 `_embed_chart_image()` 阈值判断 | export_report.py | ~25 行 | P1 | #1 |
| 3 | SVG 透明背景 + 暗色模式适配 | export_report.py | ~15 行 | P1 | #1 |
| 4 | MarkdownBlock 容器排版样式 | MarkdownBlock.tsx | ~20 行 CSS | P0 | 无 |
| 5 | `render_ui_tool` 增加 `sequence` 参数 | render_ui_tool.py | ~15 行 | P0 | 无 |
| 6 | `UIBlock` 接口增加 `sequence` 字段 | store.ts | ~5 行 | P0 | #5 |
| 7 | `render_ui_tool` 增加 `functional_interaction` 参数 | render_ui_tool.py | ~20 行 | P2 | 无 |
| 8 | TTL 从 1h 延长到 24h | genui_persistence.py | ~5 行 | P1 | 无 |
| 9 | SOUL.md 迁至单 MarkdownBlock 输出 | SOUL.md | ~50 行 | P0 | #1 |
| 10 | 导出表单标记 `functional_interaction=true` | SOUL.md | ~5 行 | P2 | #7 |
| 11 | 验证 `![alt](data:image/svg+xml;base64,...)` 在 streamdown 的渲染 | 手动测试 | ~15 min | P0（阻塞） | 无 |
| 12 | GenUIRenderer 中 block 按 `sequence` 排序 | GenUIRenderer.tsx | ~10 行 | P0 | #6 |
| 13 | 字体加载（Google Fonts + Bunny CDN） | layout.tsx 或 _document.tsx | ~5 行 | P1 | 无 |

**工作量估算**：总计约 ~200 行代码 + 手动验证。人工团队约 3-4 天，CC+gstack 约 1-2 小时。

### 12.3 废弃项清单

随新方案上线后可以移除或不再使用的部分：

| 废弃项 | 原因 | 处理方式 |
|--------|------|---------|
| CardBlock 在日报中的使用 | 卡片数据改为 Markdown 表格行 | SOUL.md 中移除相关 `render_ui` 调用 |
| EChartBlock 在日报中的使用 | 图表改为后端 SVG 内嵌 Markdown | SOUL.md 中移除相关 `render_ui` 调用；前端 EChartBlock 组件保留（其他功能可能使用） |
| TableBlock 在日报中的使用 | 数据表格改为 Markdown 表格 | SOUL.md 中移除相关 `render_ui` 调用；前端 TableBlock 组件保留 |
| 前端 ECharts 日报截图逻辑 | 导出时图表为 SVG，可直接写入 | 如存在截图代码，标记 deprecated |
| 多 Block 历史恢复逻辑 | 恢复对象从 N 个 Block 简化为 1 个 MarkdownBlock | history.ts 逻辑自动简化，无需显式删除 |
| 图表前端暗色主题切换（日报部分） | 暗色由 SVG 后端适配或 CSS 覆盖处理 | 日报 EChartBlock 移除后自然消失 |

> **注意**：CardBlock、EChartBlock、TableBlock 组件本身**不删除**，因为其他 Agent 可能使用。只是日报不再依赖它们。

### 12.4 风险清单

| # | 风险 | 等级 | 影响 | 缓解措施 |
|---|------|------|------|---------|
| R1 | Sanitizer 剥离 HTML 标签导致图片丢失 | **CRITICAL** | 报告图片全部不可见 | 使用 Markdown `![]()` 语法，已在 §8.4/§9.2 详细论证 |
| R2 | SVG base64 data URI 过大阻塞渲染 | **MEDIUM** | 多图场景下 Markdown 内容体积膨胀 | 50KB 阈值分界：小图内嵌，大图走 artifact |
| R3 | streamdown 对 `data:image/svg+xml;base64,...` URI 的支持 | **MEDIUM** | 图片渲染失败 | Phase 1 第一步验证。如不支持，降级为 artifact 远程引用 |
| R4 | 中文在 SVG 中的字体渲染 | **MEDIUM** | 图表中文标签显示为方块 | `trend_chart_to_svg()` 指定 `font-family="Noto Sans SC, sans-serif"`；沙箱预装中文字体 |
| R5 | 暗色模式下 SVG 可读性 | **MEDIUM** | 深色文字在暗色背景上看不清 | SVG 采用透明背景 + CSS `img[src*="svg"]` 覆盖 |
| R6 | PDF 导出中 SVG 图片渲染 | **LOW** | PDF 中图表缺失或变形 | weasyprint 原生支持 SVG；降级为 PNG 截图（如需要） |
| R7 | 窄屏幕下 Markdown 表格溢出 | **LOW** | 移动端表格横向滚动 | `overflow-x: auto` 包裹表格容器 |

### 12.5 实施阶段

#### Phase 1 — 基础验证与核心改造（P0，阻塞项）

**目标**：验证 Markdown 图片语法可行性 + 改造核心输出路径。

| 步骤 | 文件 | 改动 |
|------|------|------|
| 1.1 | — | **手动测试**：在 MarkdownBlock 中渲染 `![test](data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxMDAiIGhlaWdodD0iMTAwIj48cmVjdCB3aWR0aD0iMTAwIiBoZWlnaHQ9IjEwMCIgZmlsbD0iI0ZGNkIzNSIvPjwvc3ZnPg==)` 确认渲染 |
| 1.2 | export_report.py | `render_markdown()` 中 `<img src="data:...">` → `![alt](data:...)` |
| 1.3 | SOUL.md | Round 2 回调：多个 `render_ui` 调用 → 单个 `render_ui(component="markdown", content=report_markdown)` |
| 1.4 | MarkdownBlock.tsx | 添加日报容器样式类（`max-w-[800px]`、`mx-auto`、排版间距） |
| 1.5 | store.ts | `UIBlock` 接口新增 `sequence?: number` |
| 1.6 | render_ui_tool.py | 新增 `sequence: int | None` 参数，透传至 block 数据 |
| 1.7 | GenUIRenderer.tsx | 渲染前按 `sequence` 升序排列 blocks |

#### Phase 2 — 质量增强（P1，非阻塞）

**目标**：暗色模式适配 + TTL 延长 + SVG 大图阈值。

| 步骤 | 文件 | 改动 |
|------|------|------|
| 2.1 | export_report.py | `trend_chart_to_svg()` SVG 背景改为 `fill="transparent"` |
| 2.2 | export_report.py | 新增 `_embed_chart_image()` 函数，50KB 阈值分界 |
| 2.3 | genui_persistence.py | TTL 从 3600s → 86400s |
| 2.4 | layout.tsx | 添加字体 `<link>` 标签（Source Sans 3、DM Sans、JetBrains Mono、Noto Sans SC） |
| 2.5 | tailwind.css | 添加日报排版相关 CSS 变量和工具类 |

#### Phase 3 — 导出增强（P2）

**目标**：导出表单不随历史会话禁用 + artifact 大图引用。

| 步骤 | 文件 | 改动 |
|------|------|------|
| 3.1 | render_ui_tool.py | 新增 `functional_interaction: bool = False` 参数 |
| 3.2 | SOUL.md | 导出表单 `render_ui` 添加 `functional_interaction=True` |
| 3.3 | store.ts | `UIBlock` 接口新增 `functional_interaction?: boolean` |
| 3.4 | 前端渲染 | `functional_interaction=true` 的 form block 在历史会话中保持可用 |

#### Phase 4 — 编辑与打磨（P2，与 Phase 3 并行）

**目标**：Markdown 内容直接编辑 + PDF 导出完善。

| 步骤 | 文件 | 改动 |
|------|------|------|
| 4.1 | MarkdownBlock.tsx | 增加编辑模式：工具栏"编辑"按钮 → textarea 源码视图 → "保存"/"取消"按钮，见 §8.9 |
| 4.2 | MarkdownBlock.tsx | 编辑保存逻辑：更新 Zustand store 中的 `block.props.content`，触发重新渲染 |
| 4.3 | — | PDF 导出 SVG 兼容性测试和降级方案 |

### 12.6 数据流对比

#### 改造前（旧方案）

```
用户参数 (4 forms)
    │
    ▼
Agent: daily_kpi.py → daily_kpi.json
    │
    ├─→ render_ui(component="card", ...)       → CardBlock      ┐
    ├─→ render_ui(component="card", ...)       → CardBlock      │
    ├─→ render_ui(component="echart", ...)     → EChartBlock    │  7-10 个独立
    ├─→ render_ui(component="table", ...)      → TableBlock     │  GenUI Block
    ├─→ render_ui(component="table", ...)      → TableBlock     │
    ├─→ render_ui(component="markdown", ...)   → MarkdownBlock  ┘
    └─→ render_ui(component="form", ...)       → FormBlock (export)

导出: export_report.py 独立组装 → 与聊天界面两套渲染路径
历史恢复: N 个 Block 需要逐一恢复状态
```

#### 改造后（新方案）

```
用户参数 (4 forms)
    │
    ▼
Agent: daily_kpi.py → daily_kpi.json
    │
    ├─→ export_report.render_markdown(payload)  ← 后端组装完整 Markdown
    │       │
    │       ├─ trend_chart_to_svg() → SVG string
    │       └─ _embed_chart_image() → ![alt](data:...) 或 artifact 引用
    │
    ├─→ render_ui(component="markdown", content=report_md)  → MarkdownBlock (唯一)
    └─→ render_ui(component="form", functional_interaction=true) → FormBlock (export)

导出: 同一份 Markdown 内容直接写入文件 → 聊天界面与导出统一渲染路径
历史恢复: 1 个 MarkdownBlock + 1 个 FormBlock 即可恢复完整会话
```

**关键收益**：
- Block 数量：7-10 个 → 2 个（1 MarkdownBlock + 1 FormBlock）
- 前端需要维护的日报组件：CardBlock + EChartBlock + TableBlock + MarkdownBlock → 仅 MarkdownBlock
- 导出与聊天界面：两套渲染路径 → 同一份 Markdown，直展直写
- 历史恢复复杂度：N 个 Block 状态恢复 → 1 段 Markdown 文本恢复
- 图表渲染：依赖前端 ECharts 实例 → 后端 Python SVG，无前端 ECharts 依赖

---

## 13. 参考

| 模块 | 文件 |
|------|------|
| 日报 SOUL | [agents/builtin/ai-report--daily/SOUL.md](../../agents/builtin/ai-report--daily/SOUL.md) |
| 导出脚本（含 SVG 渲染 + Markdown 生成） | [skills/custom/data-analyst/scripts/export_report.py](../../skills/custom/data-analyst/scripts/export_report.py) |
| KPI 计算脚本 | [skills/custom/data-analyst/scripts/daily_kpi.py](../../skills/custom/data-analyst/scripts/daily_kpi.py) |
| FormBlock 组件 | [frontend/src/components/genui/FormBlock.tsx](../../frontend/src/components/genui/FormBlock.tsx) |
| MarkdownBlock 组件 | [frontend/src/components/genui/MarkdownBlock.tsx](../../frontend/src/components/genui/MarkdownBlock.tsx) |
| 功能改造计划 | [docs/plans/2026-05-15-daily-report-render-evaluation-and-fix.md](./2026-05-15-daily-report-render-evaluation-and-fix.md) |
| 竞品参考 | Grafana Saga Design System、Datadog Dashboards、Metabase BI |
