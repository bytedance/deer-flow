# P2 — DeerFlow 品牌资产删除/替换 清单

- 日期：2026-05-17
- 状态：实施前盘点（动手前必做）
- 目标：把仓库中所有 **DeerFlow / 鹿头 / deerflow.tech / bytedance/deer-flow** 品牌资产**完全替换**为 EHM 品牌
- 关联：[2026-05-17-ehm-redesign-plan.md §5](./2026-05-17-ehm-redesign-plan.md)

---

## 0. 命名约定（已敲定，2026-05-17）

| 项 | 值 |
|---|---|
| 产品中文名 | **EHM AI 工作台** |
| 产品英文名 | **EHM AI Workspace** |
| 短名（metadata title）| **EHM AI 工作台** |
| 产品域名 | **inscphm.com** |
| 产品 logo | **暂用文字 logo**（顶部直接渲染 "EHM AI 工作台"）|
| 默认 favicon | **占位 "E" 字 SVG**（待出图后替换）|
| 支持邮箱 | **support@inscphm.com** |
| 文档/反馈入口 | **隐藏**（MDX 文档从 build 排除）|
| 公司版权署名 | **© {year} 沈阳因思科技有限公司** |
| `package.json` name | `ehm-workspace-frontend` |
| 内部标识符策略 | **全部保留**（X-DeerFlow-Tenant header / deerflow.* localStorage keys 与 backend 协议绑定）|

---

## 1. 必须删除（直接删文件 / 字段 / DOM 引用）

### 1.1 视觉资产（删文件）

| 路径 | 现状 | 处置 |
|---|---|---|
| [frontend/public/images/deer.svg](frontend/public/images/deer.svg) | 鹿头 logo SVG（hero / login / setup 三处用作 mask）| **删除** |
| [frontend/public/images/21cfea46-34bd-4aa6-9e1f-3009452fbeb9.jpg](frontend/public/images/21cfea46-34bd-4aa6-9e1f-3009452fbeb9.jpg) | Doraemon 案例缩略图 | **删除** |
| [frontend/public/images/3823e443-4e2b-4679-b496-a9506eae462b.jpg](frontend/public/images/3823e443-4e2b-4679-b496-a9506eae462b.jpg) | Fei Fei Li 案例缩略图 | **删除** |
| [frontend/public/images/4f3e55ee-f853-43db-bfb3-7d1a411f03cb.jpg](frontend/public/images/4f3e55ee-f853-43db-bfb3-7d1a411f03cb.jpg) | Pride and Prejudice 案例缩略图 | **删除** |
| [frontend/public/images/7cfa5f8f-a2f8-47ad-acbd-da7137baf990.jpg](frontend/public/images/7cfa5f8f-a2f8-47ad-acbd-da7137baf990.jpg) | 2026 Agent Trends 案例缩略图 | **删除** |
| [frontend/public/images/ad76c455-5bf9-4335-8517-fc03834ab828.jpg](frontend/public/images/ad76c455-5bf9-4335-8517-fc03834ab828.jpg) | Titanic 案例缩略图 | **删除** |
| [frontend/public/images/d3e5adaf-084c-4dd5-9d29-94f1d6bccd98.jpg](frontend/public/images/d3e5adaf-084c-4dd5-9d29-94f1d6bccd98.jpg) | YC 视频案例缩略图 | **删除** |
| [frontend/public/favicon.ico](frontend/public/favicon.ico) | DeerFlow favicon | **替换**为 EHM favicon |
| [frontend/public/demo/threads/](frontend/public/demo/threads/) 11 个 thread 目录 | 静态网站演示用的 demo 数据（哆啦A梦、PnP、YC 等）| **整目录删除**（仅当 `NEXT_PUBLIC_STATIC_WEBSITE_ONLY=true` 才用，对内部部署无意义）|

### 1.2 着陆页板块组件（不再被引用，整文件删除）

> 这 7 个文件全是 DeerFlow 着陆页专用、与产品形态强绑定，无法平移到 EHM。直接删除并把 `app/page.tsx` 重写。

| 路径 | 内容 |
|---|---|
| [frontend/src/components/landing/hero.tsx](frontend/src/components/landing/hero.tsx) | Galaxy 星空 + WordRotate "Vibe Coding/Do Anything" + BytePlusIcon |
| [frontend/src/components/landing/sections/case-study-section.tsx](frontend/src/components/landing/sections/case-study-section.tsx) | 6 个消费 AI 案例 |
| [frontend/src/components/landing/sections/skills-section.tsx](frontend/src/components/landing/sections/skills-section.tsx) | "Agent Skills loaded progressively"通用文案 |
| [frontend/src/components/landing/sections/sandbox-section.tsx](frontend/src/components/landing/sections/sandbox-section.tsx) | "AIO Sandbox" 开发者向叙事 + 假终端 |
| [frontend/src/components/landing/sections/whats-new-section.tsx](frontend/src/components/landing/sections/whats-new-section.tsx) | DeerFlow 2.0 升级文案 |
| [frontend/src/components/landing/sections/community-section.tsx](frontend/src/components/landing/sections/community-section.tsx) | "Star on GitHub / Contribute Now" + AuroraText |
| [frontend/src/components/landing/progressive-skills-animation.tsx](frontend/src/components/landing/progressive-skills-animation.tsx) | mRNA / 论文 / 部署的复杂动画演示 |

### 1.3 可选删除的视觉装饰组件（视情况）

> 如果新着陆页 100% 不用，建议**留文件不删**（避免 lint 失败、后续 dev demo 还想用）。但**业务路径里的所有 import 必须删干净**。

| 文件 | 是否在 EHM 主线使用 | 处置 |
|---|---|---|
| `components/ui/galaxy.tsx` | 否 | 留文件，删使用点 |
| `components/ui/flickering-grid.tsx` | 否 | 留文件，删使用点 |
| `components/ui/aurora-text.tsx` | 否（welcome/community 都删了）| 留文件，删使用点 |
| `components/ui/word-rotate.tsx` | 否 | 留文件，删使用点 |
| `components/ui/confetti-button.tsx` | 否 | 留文件，删使用点 |
| `components/ui/number-ticker.tsx` | 仅 GitHub Star 计数用 | 留 |
| `components/landing/footer.tsx` | 仍要用（改写） | 改写，不删 |
| `components/landing/header.tsx` | 仍要用（改写） | 改写，不删 |
| `components/landing/section.tsx` | 仍要用（通用 section 容器） | 改写或保留 |

### 1.4 globals.css 装饰样式段（删除）

[frontend/src/styles/globals.css](frontend/src/styles/globals.css) 删除以下段落：

| 行 | 内容 | 说明 |
|---|---|---|
| 78–86 | `--animate-fade-in` + `@keyframes fade-in` | 仅装饰，留 base transition 即可 |
| 99–105 | `--animate-bouncing` + `@keyframes bouncing` | "skeleton dots"装饰 |
| 131–146 | `--animate-wave` + `@keyframes wave` | `welcome.tsx` 招手动画 |
| 188–222 | `--animate-aurora` + `--animate-shine` + `@keyframes` | AuroraText / Shine |
| 379–432 | `.ambilight` 类 + `@keyframes ambilight` | 彩虹环境光（当前没人用） |
| 438–444 | `.golden-text` 类 | Ultra 模式金色文字 |

**保留**：`--font-sans` 定义（P3 改）、`@theme inline` shadcn 变量、`:root`/`.dark` 主题、`base.* { … border-border }`、`.daily-report` 段（日报功能用）。

---

## 2. 必须改写（保留文件，全文重写）

### 2.1 着陆页主入口

| 路径 | 现状 | 重写为 |
|---|---|---|
| [frontend/src/app/page.tsx](frontend/src/app/page.tsx) | `<Hero/> <CaseStudySection/> <SkillsSection/> <SandboxSection/> <WhatsNewSection/> <CommunitySection/>` 6 板块 | 一个简洁的 EHM 着陆页：title + 一句话 subtitle + 进入工作台 CTA + 极简业务能力概览（4 卡，纯文字）+ 一句技术底座说明（不提 DeerFlow）+ Footer |

### 2.2 顶部 Header / 底部 Footer

| 路径 | 删 | 改 |
|---|---|---|
| [frontend/src/components/landing/header.tsx](frontend/src/components/landing/header.tsx) | 行 1: `StarFilledIcon, GitHubLogoIcon` 全 import；行 30: `homeURL ?? "https://github.com/bytedance/deer-flow"`；行 34: `<h1>DeerFlow</h1>`；行 51–76: GitHub Star 按钮（含粉紫渐变 + StarCounter API 调用）；行 82–116: `StarCounter` 子组件 | h1 改 `{PROD_NAME_CN}` 或 logo SVG；右侧不再放 GitHub 按钮，改为"进入工作台"主 CTA；删除 GitHub API 调用 |
| [frontend/src/components/landing/footer.tsx](frontend/src/components/landing/footer.tsx) | 行 21: `"Originated from Open Source, give back to Open Source."`；行 25–26: `Licensed under MIT License` / `© {year} DeerFlow` | 改为 `© {year} {COMPANY}` + 备案号（中国部署需要）+ 客户支持联系方式（可选）|

### 2.3 登录 / Setup 页（所有 DeerFlow 视觉元素清除）

| 路径 | 删 | 改 |
|---|---|---|
| [frontend/src/app/(auth)/login/page.tsx](frontend/src/app/(auth)/login/page.tsx) | 行 9: `import { FlickeringGrid }`；行 186–193: 鹿头蒙版 FlickeringGrid 整段；行 196: `<h1>DeerFlow</h1>` | h1 改 `{PROD_NAME_CN}`；背景从鹿头闪烁去掉；如果想保留视觉留白，用一个静态工业图样 SVG（管线/反应器轮廓极淡水印）|
| [frontend/src/app/(auth)/setup/page.tsx](frontend/src/app/(auth)/setup/page.tsx) | 行 160 / 169 / 231 / 240：两处 `mask-[url(/images/deer.svg)]` + 两处 `<h1>DeerFlow</h1>` | 同 login 处理 |

### 2.4 Workspace 内部品牌

| 路径 | 删 | 改 |
|---|---|---|
| [frontend/src/components/workspace/welcome.tsx](frontend/src/components/workspace/welcome.tsx) | 行 9: `import { AuroraText }`；行 47: `<AuroraText>`；行 11: `let waved = false`；行 29–31: `useEffect` + `animate-wave`；行 44: `{isUltra ? "🚀" : "👋"}` | 改为静态欢迎："你好，{user_name ?? '欢迎'}"。删除 emoji、wave 动画、AuroraText、`isUltra` 分支的金色色阶 |
| [frontend/src/components/workspace/input-box.tsx](frontend/src/components/workspace/input-box.tsx) | 行 49: `import { ConfettiButton }`；行 1444–1451: `<ConfettiButton><SparklesIcon/> Surprise Me</ConfettiButton>` 整段；行 1035 / 1041 / 1160 / 1163 等 `golden-text` / `text-[#dabb5e]` 装饰 | 删 SurpriseMe；Ultra 模式不再用 golden-text，改普通字色 + RocketIcon 即可 |
| [frontend/src/components/workspace/workspace-nav-menu.tsx](frontend/src/components/workspace/workspace-nav-menu.tsx) | 行 103–112: "officialWebsite → deerflow.tech"；行 113–122: "visitGithub → bytedance/deer-flow"；行 124–133: "reportIssue → deer-flow/issues"；行 134–139: "contactUs → support@deerflow.tech"；行 142–150: "about" 入口（可选保留）| 删除前 4 个外链。"about" 入口要么删除，要么改为内部"关于本系统"文档。视情况保留"reportIssue"为内部工单 URL |
| [frontend/src/components/workspace/workspace-container.tsx](frontend/src/components/workspace/workspace-container.tsx) | 行 95–104: 顶部右侧 "GithubIcon → bytedance/deer-flow" 链接 | **删除**整个 GithubIcon 链接（工业部署没必要露出 GitHub 入口） |
| [frontend/src/components/workspace/recent-chat-list.tsx](frontend/src/components/workspace/recent-chat-list.tsx) | 行 121: `const VERCEL_URL = "https://deer-flow-v2.vercel.app";` | 改为内部生产域名常量，或直接删分享功能（演示用）|
| [frontend/src/components/workspace/settings/about-content.ts](frontend/src/components/workspace/settings/about-content.ts) | 整个 `aboutMarkdown` 全是 DeerFlow 的 README 内容（🦌 / star history / @hetaoBackend / @magiccube）| **整体重写**为内部"关于本系统"或**直接删除**这个 settings 项 |
| [frontend/src/components/workspace/settings/about.md](frontend/src/components/workspace/settings/about.md) | 同上（注释里说是 about-content.ts 的源 markdown）| 同上处理 |
| [frontend/src/components/workspace/settings/memory-settings-page.tsx](frontend/src/components/workspace/settings/memory-settings-page.tsx) 行 392 | 文件名 `deerflow-memory-...json` | 改 `ehm-memory-...json`（仅文件名习惯）|
| [frontend/src/app/workspace/agents/new/page.tsx](frontend/src/app/workspace/agents/new/page.tsx) 行 51 | localStorage key `deerflow.agent-create.save-hint-seen` | 可保留（用户不可见）。如要洁癖：迁移 key（双读：先读旧 key，写入新 key）|

### 2.5 i18n 文案

[frontend/src/core/i18n/locales/zh-CN.ts](frontend/src/core/i18n/locales/zh-CN.ts) + [frontend/src/core/i18n/locales/en-US.ts](frontend/src/core/i18n/locales/en-US.ts) 同步改：

| 字段 | 旧 | 新 |
|---|---|---|
| `agentCreate.saveRequestedDescription` (zh:219) | "已提交保存请求，**DeerFlow** 正在根据当前对话生成并保存初版智能体。" | "已提交保存请求，系统正在根据当前对话生成并保存初版智能体。" |
| `agentCreate.notReadyDescription` (zh:225) | "智能体已创建，但 **DeerFlow** 暂时还无法读取到它…" | "智能体已创建，但系统暂时还无法读取到它…" |
| `workspace.officialWebsite` (zh:325) | "访问 **DeerFlow** 官方网站" | **删除该字段**（外链已删）|
| `workspace.githubTooltip` (zh:326) | "访问 DeerFlow 的 Github 仓库" | **删除** |
| `workspace.visitGithub` (zh:328) | "在 Github 上查看 DeerFlow" | **删除** |
| `workspace.about` (zh:331) | "关于 **DeerFlow**" | "关于系统" 或 删除 |
| `workspace.skillInstallTooltip` (zh:373) | "...使其可在 **DeerFlow** 中使用" | "...使其可在工作台中使用" |
| `settings.keyboardShortcutsDescription` (zh:432) | "使用键盘快捷键更快地操作 **DeerFlow**。" | "使用键盘快捷键更快操作。" |
| `settings.appearance.description` (zh:440) | "根据你的偏好调整 **DeerFlow** 的界面和行为。" | "根据你的偏好调整界面和行为。" |
| `settings.memory.description` (zh:454) | "**DeerFlow** 会在后台不断从你的对话中自动学习…" | "系统会在后台不断从你的对话中自动学习…" |
| `settings.skills.installInstruction` (zh:550) | "...放在 **DeerFlow** 根目录下…" | "...放在系统根目录下…" |
| `settings.notification.description` (zh:556) | "**DeerFlow** 只会在窗口不活跃时…" | "系统只会在窗口不活跃时…" |
| `settings.notification.testTitle` (zh:561) | "**DeerFlow**" | `{PROD_NAME_CN}` |
| `welcome.greeting` (zh:63) | "你好，欢迎回来！" | 保留（已经是泛化文案） |
| **建议同步替换的工业语境**：`inputBox.suggestions[]`、`inputBox.surpriseMePrompt` | 通用 / 哆啦A梦风 | 改为 §6.2 列出的工业问题；`surpriseMe` 整段可考虑删除 |

英文 (en-US.ts) 同步：约 14 处直接 `s/DeerFlow//` 或改成 `the system / EHM Workspace`。

### 2.6 metadata / SEO

| 路径 | 改 |
|---|---|
| [frontend/src/app/layout.tsx](frontend/src/app/layout.tsx) 行 11–12 | `title: "{PROD_NAME_CN}"`；`description: "{PROD_NAME_EN} — 设备健康管理 AI 工作台"`；行 22–27 删除 Google Fonts `<link>`（P3 自托管字体替代）|
| [frontend/next.config.js](frontend/next.config.js) | 添加/调整 `metadataBase: new URL('https://{DOMAIN}')` |
| [frontend/package.json](frontend/package.json) `name` | `"deer-flow-frontend"` → `"ehm-workspace-frontend"`（影响 ci 工件名 / docker image tag）|
| [frontend/src/app/blog/layout.tsx](frontend/src/app/blog/layout.tsx) 行 16 | `docsRepositoryBase` 指向 `bytedance/deerflow` → 删除 blog（见 §3）或指向内部 |
| [frontend/src/app/(auth)/setup/page.tsx](frontend/src/app/(auth)/setup/page.tsx) 全文 | 上游 setup 向导文案里多处提到 DeerFlow → 改 `{PROD_NAME_CN}` |

### 2.7 内部 header / 标识符（**保留为 internal 标识，不可见，不强制改**）

> 这些是程序内部用的标识符，用户看不到，改了反而增加上游升级合并冲突。**建议保留**。

| 路径 | 内容 | 处置 |
|---|---|---|
| `core/api/fetch-gateway.ts` 行 6 / 注入的 header | `X-DeerFlow-Tenant` HTTP header | **保留**，与 backend 协议绑定 |
| `core/tenant/store.ts` 行 96 | 同上 | **保留** |
| `core/tenant/types.ts` 行 3 | localStorage key `deerflow.tenant-id` | **保留**（迁移成本 > 价值）|
| `core/settings/local.ts` 行 22–24 | `deerflow.local-settings` 等 localStorage key | **保留** |
| `app/(auth)/login/page.tsx` 行 160 | `"X-DeerFlow-Tenant": tenantId` | **保留** |
| `app/api/memory/[...path]/route.ts` 行 17–19 / `app/api/memory/route.ts` | 同上 header | **保留** |
| `core/api/stream-mode.ts` 行 32 | console 日志 `[deer-flow]` | **保留**或改 `[ehm]` |
| `core/agents/api.ts` 行 91 / 103 | error message "Could not reach the DeerFlow backend." | **改**为 "Could not reach the backend." |
| `core/messages/usage-model.ts` 行 70 | 注释引用 backend 路径 `backend/packages/harness/deerflow/...` | **保留** |
| `.env.example` 行 20–21 | `DEER_FLOW_INTERNAL_GATEWAY_BASE_URL` / `DEER_FLOW_TRUSTED_ORIGINS` | **保留**（与 backend env schema 绑定）|

> 这条策略的关键：**用户可见 = 必须改；与 backend 协议/上游升级强绑定 = 不改**。

---

## 3. 文档 / Blog / MDX 内容（建议直接隐藏）

`frontend/src/content/{en,zh}/` 下有 51 个 MDX 文件，全部是上游 DeerFlow 的开发者文档（harness / sandbox / skills / memory / lead-agent / why-deerflow…）。这部分对 EHM 终端用户**完全无意义**，且改写工作量极大。

**推荐处置：**

| 选项 | 说明 |
|---|---|
| **A（推荐）** | 在 `next.config.js` 或路由里**禁用 `/[lang]/docs` 和 `/blog` 路由**（404 或重定向到 `/`），保留源文件不动以便后续上游升级 |
| B | 把 `src/content/` 整个目录排除出 build（修改 nextra 配置或直接重命名目录）|
| C | 大返工：把所有 MDX 改写为 EHM 用户文档（成本极高，不推荐）|

**附带改动（如选 A）：**
- 删除 `app/blog/` 路由组（或加路由级 `notFound()`）
- 删除 `app/[lang]/docs/` 路由组（或同上）
- 删除 header 里 `Docs` / `Blog` 的导航链接（`landing/header.tsx` 行 38–50 的 `<nav>`）
- i18n 里 `t.home.docs` / `t.home.blog` 文案删除

---

## 4. E2E 测试

| 路径 | 改 |
|---|---|
| [frontend/tests/e2e/landing.spec.ts](frontend/tests/e2e/landing.spec.ts) 行 11 | `page.locator("header h1", { hasText: "DeerFlow" })` → `{ hasText: "{PROD_NAME_CN}" }` |
| [frontend/tests/e2e/chat.spec.ts](frontend/tests/e2e/chat.spec.ts) 行 23–24, 47 | "Hello, DeerFlow!" / "Hello from DeerFlow!" → "Hello, EHM!" 之类（仅测试 fixture，不影响产品）|
| [frontend/tests/e2e/utils/mock-api.ts](frontend/tests/e2e/utils/mock-api.ts) 行 265, 285 | mock 流返回的 "Hello from DeerFlow!" → 同步改 |

---

## 5. 仓库根 / 顶层文件（前端目录之外）

| 路径 | 处置 |
|---|---|
| `README.md`（仓库根）| 不动（这是上游 OSS 文档；如果要做内部 fork，改写成 EHM 部署说明）|
| `frontend/README.md` | 改写为 EHM 前端开发说明（短）|
| `frontend/AGENTS.md` | 提到 DeerFlow 的 2 处：行 5 和行 108。改为中性描述。 |
| `frontend/CLAUDE.md` | 文件本身是给 Claude Code 看的，提到 DeerFlow 是事实陈述（"the project is a fork of DeerFlow"），保留不删 |
| `frontend/package.json` `name` | 改为 `ehm-workspace-frontend`（见 §2.6）|

---

## 6. 实施顺序（建议 2 个独立 PR）

### PR-A：用户可见品牌替换（1.5 天）

含 §1.1, §1.2, §1.3 删除使用点, §1.4, §2.1, §2.2, §2.3, §2.4, §2.5, §2.6, §3 选项 A, §4

**验收：**
- [ ] 全站任意路由不再出现 "DeerFlow" / 鹿头 / 紫粉渐变 / Galaxy 星空
- [ ] 设置→关于：要么是内部"关于本系统"，要么没有这个入口
- [ ] 顶部、侧栏、底部、登录、setup 页都是 `{PROD_NAME_CN}` 品牌
- [ ] favicon 已替换
- [ ] `<title>` 是 `{PROD_NAME_CN}`，`<meta description>` 与 EHM 相关
- [ ] `pnpm test:e2e` 通过

### PR-B：用户不可见的"洁癖级"清理（可选，0.5 天）

含 §2.7 中 `console.log` 前缀 / `error message` 这类对用户不可见但开发者可见的小修。
**注意：** 不要碰 `X-DeerFlow-Tenant` 这类与 backend 协议强绑定的内容。

---

## 7. 风险与注意

| 风险 | 缓解 |
|---|---|
| 上游升级冲突 | 凡是上游会持续维护的文件（`fetch-gateway.ts`、`tenant/`、`api/memory/`、`AGENTS.md` 上半部分）只动用户可见字符串，不改结构 |
| MDX 文档全删后用户找不到帮助 | 写一份内部"关于本系统/快速开始"短文档，挂到顶部 nav 或 settings.about |
| `static-website-only` 模式下 `case-study` thread 数据被引用而崩溃 | 重写 `app/page.tsx` 时不再依赖 `public/demo/threads/`；`workspace/page.tsx` 行 9–18 的 `NEXT_PUBLIC_STATIC_WEBSITE_ONLY` 分支也要改或删 |
| localStorage key 一旦改，老用户偏好丢失 | §2.7 列出的 key **保留不改**；如果坚持要改，做"双读迁移"（首次启动从老 key 读，立刻写入新 key）|
| GitHub Star 计数 API 与 Vercel 分享 URL 失效 | §2.2 / §2.4.5 已经直接改/删 |
| 字体 Google Fonts `<link>` 在内网拉不到 | §2.6 中 `layout.tsx` 行 22–27 的 Google Fonts `<link>` 要 P3 自托管时同步删除 |

---

## 8. 数字总览（让你一眼看到工作量）

| 类别 | 数量 |
|---|---|
| 删文件 | **9 个图片** + **7 个着陆 section** = 16 个文件 |
| 删目录 | **1 个**（`public/demo/threads/`，含 11 个 thread 子目录） |
| 改写文件 | **17 个 .tsx/.ts/.md**（不含 i18n） |
| i18n 文案点 | **~14 处 zh-CN** + 同步 14 处 en-US = ~28 处 |
| 内部标识符 | **~12 处保留不改**（X-DeerFlow-Tenant、deerflow.* localStorage keys） |
| MDX 文档 | **51 个文件 → 整组路由禁用**（不删源文件） |
| E2E 测试 | **3 个 spec 文件** 文案对齐 |

总工作量：CC + gstack 协助下 **1.5–2 天**（不含 §3 选项 C 的 MDX 改写）。

---

## 9. 待你拍板（开工前）

1. §0 的 9 项命名（产品名、域名、邮箱、版权署名、logo、favicon）
2. §3 文档/Blog 处置：**A 禁用** / B 排除 build / C 全部改写
3. §2.7 的内部标识符：**全部保留**（推荐） / 全部改 / 双读迁移
4. §2.4.5 `recent-chat-list.tsx` 的"分享 thread"功能：保留并改内部域名 / 直接删
5. §2.6 `package.json name` 是否改（影响 docker tag、ci 产物）
6. 是否做 PR-B（洁癖级清理）
