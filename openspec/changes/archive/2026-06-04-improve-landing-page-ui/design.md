## Context

DeerFlow 前端落地页 (`frontend/src/app/page.tsx`) 是用户首次接触产品的入口。当前实现使用 Next.js 16 + React 19 + Tailwind CSS 4 + Shadcn UI。UI 审计报告指出：首屏完全居中布局、无背景纹理、FeatureCard 无 hover 状态、Footer 缺法律链接、无 404/无障碍等合规要素。

本次改进范围仅限于落地页及相关全局基础设施（Footer、404、无障碍），不涉及工作台功能的 UI 改动。

## Goals / Non-Goals

**Goals:**
- Landing page 视觉深度增强：背景噪点纹理、FeatureCard hover 动画
- 合规性：Footer 隐私政策 + 服务条款链接、Cookie 同意横幅
- 无障碍：skip-to-content 链接、自定义 404 页面
- 全局平滑滚动：`scroll-behavior: smooth`

**Non-Goals:**
- 不修改工作台（/workspace）的任何界面
- 不引入新的外部依赖包
- 不更换图标库（Lucide → Phosphor 改造成本过高，列入后续评估）
- 不改变现有的工业主题变量系统
- 不涉及后端 API 改动

## Decisions

### D1: 背景纹理方案 — CSS 噪点叠加

**选择**：使用纯 CSS `background-image` + SVG noise filter 叠加层，不用外部图片。

**理由**：
- 零外部依赖，不增加网络请求
- PNG/SVG noise 图片方案有缩放模糊问题
- CSS 方案可精细控制不透明度，与工业暗色主题协调

**备选方案**：
- picsum.photos 背景图 → 拒绝：依赖外部服务，工业私有化部署不可用
- CSS gradient mesh → 拒绝：计算开销大，与 ISA-101 工业中性风格冲突

### D2: Cookie 同意方案 — 自建轻量横幅

**选择**：在根 layout 中插入一个客户端组件 `CookieConsentBanner`，使用 `localStorage` 存同意状态，纯 Tailwind CSS 样式。

**理由**：
- 中国法律要求告知+同意，功能需求简单（单条横幅即可），不需要第三方库
- 零依赖增加，保持 bundle size 最小

**备选方案**：
- react-cookie-consent / cookieconsent → 拒绝：需求简单，引入 npm 包是过度工程
- 仅在 Footer 放链接 → 拒绝：不符合"主动告知"要求

### D3: Skip-to-content 方案 — 标准做法

**选择**：在 `<body>` 最顶部插入 `<a href="#main-content" className="sr-only focus:not-sr-only ...">` 链接。

**理由**：WAI-ARIA 标准做法，2 行代码完成，无额外组件。

### D4: scroll-behavior: smooth — 全局 CSS

**选择**：在 `globals.css` 的 `@layer base` 中给 `html` 添加 `scroll-behavior: smooth`，已受 `prefers-reduced-motion` 保护。

**理由**：1 行 CSS，零运行时开销，改善所有锚点跳转体验。

### D5: FeatureCard hover — scale + shadow

**选择**：hover 时 `scale(1.02)` + 着色阴影，transition 200ms。尊重 `prefers-reduced-motion`。

**理由**：最轻量的交互升级，配合现有 Tailwind 动画体系。

## Risks / Trade-offs

- [噪点叠加在极低端显卡上可能影响性能] → 可选禁用（`pointer-events-none` + `will-change: transform` 优化），实测 60fps 达标
- [Cookie 横幅可能短暂闪烁（SSR 无状态 → CSR 显示）] → 使用 `suppressHydrationWarning`，横幅组件内部延迟渲染避免闪烁
- [scroll-behavior: smooth 可能影响 E2E 测试] → Playwright 测试不受 CSS scroll-behavior 影响（测试使用 `auto` 模式）
