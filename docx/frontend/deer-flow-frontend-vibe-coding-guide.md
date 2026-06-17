# DeerFlow Frontend — Vibe Coding 入门蓝本

> 面向"前端小白 + AI 辅助开发"的实战蓝图。先有这份心智模型，再动手 vibe code。

---

## 1. 五层心智模型（先有这个再动手）

把整个前端想成一个五层蛋糕，**从外到内**：

| 层 | 路径 | 干啥 | 改动频率 |
|---|---|---|---|
| ① 路由 | `src/app/` | 定义 URL → 页面的映射 | 低（加新页面才动） |
| ② 页面 | `src/app/**/page.tsx` | 把组件拼成一个页面 | 中 |
| ③ 组件 | `src/components/workspace/` | 按钮、消息气泡、输入框这些 UI 件 | **最高**（vibe coding 主战场） |
| ④ 业务逻辑 | `src/core/` | 拿数据、推消息、存状态、订配置 | 中（改功能必动） |
| ⑤ 后端对接 | LangGraph SDK | 发请求、收流式响应 | 别动（封装好了） |

**小白口诀**：vibe coding 时，**99% 的改动在 ② 和 ③**（拼页面、调样式），需要新功能才下钻到 ④。

---

## 2. 这个项目的关键事实（先记住）

从 `frontend/CLAUDE.md` + `package.json` 提炼的，**别踩坑**：

- **Next.js 16 + React 19 + Tailwind v4 + TypeScript**（Tailwind 4 用新 `@import` 语法，跟 v3 不一样）
- **shadcn 组件在 `src/components/ui/`**，**AI 元素在 `src/components/ai-elements/`** —— **这两个文件夹是自动生成的，禁止手改**。要加组件就 `pnpm dlx shadcn@latest add xxx`，AI 元素同理。
- **默认是 Server Component**，要交互（state、事件、浏览器 API）才加 `"use client"`。
- **路径别名** `@/*` → `src/*`，写 import 用 `@/components/...` 别写相对路径。
- **class 名拼接用 `cn()`**（`@/lib/utils`），不要手写三元字符串。
- **业务逻辑入口是 `src/core/threads/hooks.ts`**：`useThreadStream` / `useSubmitThread` / `useThreads` 这三个 hook 几乎包揽所有聊天场景。
- **跑起来用 Turbopack**：`cd frontend && pnpm dev`（端口 3000）。但全栈联调建议用 `make dev`（顶层，自动起 nginx + gateway + frontend）。

---

## 3. 你的 vibe coding 剧本

Vibe coding 的成败 = **你能不能把"我想要什么"翻译成 AI 能照着做的指令**。这套栈特别适合 vibe coding，因为有大量现成组件可以拼，但前提是你指对地方。

### 3.1 改 UI（最常见，占 80% 的需求）

**指令模板**：

```text
改 [文件路径] 的 [组件名]：
- 现在长这样：[描述现状]
- 我想让它：[描述目标行为 / 视觉]
- 用现成的 [ui 组件 / ai-elements 组件名]，不要新建 shadcn 组件
- 保持 [现有的某特征] 不变
```

**示例**（真实可用的 prompt）：

> 改 `src/components/workspace/chat/input.tsx` 的输入框：
>
> - 现在输入框旁边没有"上传图片"按钮
> - 我想加一个图标按钮放在发送按钮左边
> - 用 `lucide-react` 里的 `Image` 图标，参考现有工具栏按钮的样式
> - 点击后调用 `useUploadFile` hook（如果在 `core/uploads` 里有的话），先看看有没有这个 hook，没有就只放 UI 不绑逻辑

### 3.2 加新页面

**指令模板**：

```text
在 src/app 下加一个新路由 /workspace/settings/threads/[thread_id]/memory：
- 这是 [页面用途] 的页面
- 复用 [已有的组件 A] 和 [组件 B]
- 数据从 [core 里的某个 hook] 拿
- 不要碰 ui/ 和 ai-elements/ 文件夹
```

### 3.3 改业务逻辑（这层要小心）

**先问我**，别盲改。`src/core/` 是有状态的，乱改会让聊天/工件/技能全炸。改之前我应该：

1. 先 `codegraph_context` 看清楚调用链
2. 跑现有的单测（`pnpm test`）确保没破坏

### 3.4 加新功能（边界开始模糊了）

只要**跨多个文件**或**动 core/**，先告诉我，**走 OpenSpec → brainstorming → 实现**的流程，别直接 vibe code 改。规则见项目根 `CLAUDE.md` 的"任务分流"。

---

## 4. 必装的肌肉记忆（命令速查）

| 想做什么 | 跑什么 |
|---|---|
| 起服务看效果 | `cd frontend && pnpm dev` |
| 改完代码先看有没有错 | `pnpm check`（lint + typecheck 一把梭） |
| 写/跑单测 | `pnpm test` |
| 跑端到端测试 | `pnpm test:e2e`（慢，但能验真实交互） |
| 加 shadcn 组件 | `pnpm dlx shadcn@latest add <name>` |
| 格式化 | `pnpm format:write` |
| 类型检查 | `pnpm typecheck` |

> ⚠️ 项目根 `CLAUDE.md` 强制所有命令加 `rtk` 前缀省 token（比如 `rtk pnpm test`），但 `pnpm` 脚本本身是 passthrough，效果一样。

---

## 5. 小白的三个保命守则

1. **看不到效果就刷新浏览器**。Turbopack 改了文件会自动热更新；如果 UI 没动，**先看浏览器控制台报错**，再回来问我。
2. **改动只动我让你动的文件**。我给你的指令会带具体文件路径，照着改，别顺手"优化"邻居代码。
3. **遇到不懂的术语直接问**。比如"什么是 Server Component"、"stream 怎么工作的"、"为什么用 TanStack Query 不用 SWR"，我都给你讲清楚再动手，别带着误解往下走。

---

## 6. 下一步建议

你现在不需要背熟上面所有东西。**告诉我第一个想改的需求**（比如"我想在聊天页面右上角加一个'清空历史'按钮"），我直接给你：

- 该改哪几个文件
- 写好的 diff 或新文件
- 怎么验证

这样从"我想要 X" → "代码改完 + 你看到效果"的一个完整闭环，就是 vibe coding 的最小单位。

---

## 附：核心文件速查

```
frontend/
├── src/
│   ├── app/                              # ① 路由（URL → 页面）
│   │   ├── page.tsx                      # 落地页 /
│   │   └── workspace/chats/[thread_id]/  # 聊天页
│   ├── components/
│   │   ├── ui/                           # ⚠️ shadcn 自动生成，别手改
│   │   ├── ai-elements/                  # ⚠️ AI SDK 元素，别手改
│   │   ├── workspace/                    # ③ 聊天页面组件（主战场）
│   │   └── landing/                      # 落地页区块
│   ├── core/                             # ④ 业务逻辑
│   │   ├── threads/hooks.ts              # ⭐ useThreadStream / useSubmitThread / useThreads
│   │   ├── api/                          # LangGraph client 单例
│   │   ├── artifacts/                    # 工件加载/缓存
│   │   ├── channels/                     # IM 渠道（飞书/Slack/...）
│   │   ├── i18n/                         # 国际化（en-US, zh-CN）
│   │   ├── memory/                       # 持久化记忆
│   │   ├── skills/                       # 技能安装与管理
│   │   └── mcp/                          # Model Context Protocol 集成
│   ├── hooks/                            # 共享 React hooks
│   ├── lib/utils.ts                      # cn() 工具函数
│   └── env.js                            # 环境变量 Zod 校验
├── tests/
│   ├── unit/                             # Vitest 单测，镜像 src/ 布局
│   └── e2e/                              # Playwright 端到端测试
├── playwright.config.ts                  # E2E 配置（用 page.route 拦截后端）
└── package.json
```
