## Why

DeerFlow 前端落地页（Landing page）当前过于扁平单调，缺乏工业产品的视觉深度和专业感，同时多项合规性和无障碍功能缺失。这些问题影响首次访问用户的品牌信任度和产品的商业成熟度感知。现在立即修复，赶在对外演示和客户交付窗口之前。

## What Changes

- **Landing page 视觉升级**：为首屏区域添加背景纹理/噪点叠加，FeatureCard 添加 hover 交互反馈，增加视觉层次
- **合规性补充**：Footer 添加隐私政策和服务条款链接，添加 Cookie 同意横幅（中国法律要求）
- **无障碍完善**：添加 skip-to-content 链接，创建自定义 404 页面
- **交互增强**：FeatureCard 添加 hover 态（背景偏移/微缩放），全局启用 `scroll-behavior: smooth`
- **组件优化**：FeatureCard 从"白色边框卡片"模式升级为更具质感的变体

## Capabilities

### New Capabilities

- `landing-visual-depth`: Landing page 视觉深度增强 — 背景纹理、FeatureCard hover 交互、布局微调
- `compliance-essentials`: 合规性基础组件 — 隐私政策/服务条款链接、Cookie 同意横幅
- `accessibility-basics`: 无障碍基础 — skip-to-content 链接、自定义 404 页面
- `interaction-polish`: 全局交互润色 — 平滑滚动、卡片 hover 反馈

### Modified Capabilities

无。所有变更均为新增能力，不修改现有 spec。

## Impact

- **受影响文件**：
  - `frontend/src/app/page.tsx` — Landing page 主页面
  - `frontend/src/components/landing/footer.tsx` — Footer 组件
  - `frontend/src/components/landing/header.tsx` — Header 组件（skip-to-content）
  - `frontend/src/app/not-found.tsx` — 新建 404 页面
  - `frontend/src/styles/globals.css` — 全局样式（scroll-behavior、纹理）
  - `frontend/src/app/layout.tsx` — 根布局（skip-to-content、Cookie 横幅）
- **新增依赖**：无外部新依赖（使用 Tailwind CSS 4 原生能力 + 现有 shadcn 组件）
- **不涉及**：后端 API、工作台功能界面、数据库
