## 1. 全局交互润色

- [ ] 1.1 在 `globals.css` 的 `@layer base` 中为 `html` 添加 `scroll-behavior: smooth`

## 2. Landing 视觉深度增强

- [ ] 2.1 在 `globals.css` 中定义 CSS noise texture keyframe / `background-image`（SVG noise filter 方案）
- [ ] 2.2 在 `page.tsx` 首屏 hero 区域添加噪点叠加层 `<div>`，使用 `pointer-events-none fixed inset-0 z-0 opacity-[0.03]`
- [ ] 2.3 将 hero section 从完全居中对齐改为桌面端左右两栏不对称布局（左侧标题+按钮，右侧可放装饰元素/背景图占位）
- [ ] 2.4 为 FeatureCard 添加 `transition-transform transition-shadow duration-200` + `hover:scale-[1.02] hover:shadow-lg` 交互
- [ ] 2.5 确保 FeatureCard hover 受 `prefers-reduced-motion` 保护（`motion-reduce:transform-none`）

## 3. 合规性基础组件

- [ ] 3.1 在 Footer 组件中添加"隐私政策"和"服务条款"链接，分组在版权信息下方
- [ ] 3.2 创建 `src/components/cookie-consent-banner.tsx` 客户端组件
- [ ] 3.3 在 `src/app/layout.tsx` 根布局中引入 CookieConsentBanner
- [ ] 3.4 CookieBanner 实现：首次访问从底部弹出，点击"我知道了"后写入 localStorage 并隐藏

## 4. 无障碍基础

- [ ] 4.1 在 `src/app/layout.tsx` 的 `<body>` 顶部添加 skip-to-content 链接（`sr-only focus:not-sr-only` 模式）
- [ ] 4.2 在 `page.tsx` 的 `<main>` 标签上添加 `id="main-content"`
- [ ] 4.3 创建 `src/app/not-found.tsx` 自定义 404 页面（含 EHM 品牌标识 + 导航回首页/工作台的链接）
- [ ] 4.4 创建 `src/app/workspace/not-found.tsx`，在工作台布局内展示 404 页面

## 5. 验证

- [ ] 5.1 `pnpm check` 通过（lint + typecheck）
- [ ] 5.2 手动验证： Landing page 噪点纹理在各分辨率下正常
- [ ] 5.3 手动验证： FeatureCard hover 在桌面端有动画、在 reduced-motion 下无动画
- [ ] 5.4 手动验证： Cookie 横幅首次显示、关闭后不再出现
- [ ] 5.5 手动验证： Tab 键可见 skip-link，激活后跳转到 main content
- [ ] 5.6 手动验证： 访问 `/nonexistent` 显示自定义 404 页面
