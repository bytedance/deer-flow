## Context

当前聊天页输入区由两个层次组成：

1. 底部绝对定位 dock：`absolute right-0 bottom-0 left-0`
2. 新对话首屏特殊 frame：`isNewThread` 时添加 `-translate-y-[calc(50vh-96px)]`

这套设计在普通浏览器直开中可以实现“欢迎语 + 输入框视觉居中”，但它对父容器首次尺寸极其敏感。EHM 中 DeerFlow 运行在 iframe 内，且宿主会：

- 在首次进入时完成额外的 iframe 装载、鉴权和内部 route 恢复
- 在标签切换时对 iframe 使用缓存与显示/隐藏

当新对话首屏在父容器尺寸尚未稳定时就按 `50vh` 计算位移，后续如果又叠加首次发送、route replace、streaming 更新或 iframe 恢复显示，就可能保留错误的布局结果。

## Goals / Non-Goals

**Goals:**

- 让 `/workspace/chats/new` 首屏不再依赖首次测量结果敏感的强位移
- 保持欢迎首屏的居中观感
- 保持普通会话页底部输入区交互不变
- 覆盖 EHM iframe 冷启动与登录后首次进入场景

**Non-Goals:**

- 不重构宿主 iframe keep-alive / route sync 主流程
- 不重构普通历史会话的消息区布局
- 不改变新对话的业务流程、deep-link、streaming 语义

## Decisions

1. **拆分新对话首屏与普通会话页的 composer 容器布局**
   - 普通会话继续使用现有底部 dock
   - 新对话首屏不再复用“底部 dock + translateY”组合，而是改为正常 flex 布局中的居中 section

2. **取消 `translateY(calc(50vh-96px))`**
   - 该位移是本次问题的高风险点，因为它依赖首轮可视区域高度
   - 改为使用容器自身的 `flex` / `justify-center` / `padding` 控制视觉位置

3. **首屏仅负责视觉居中，不再承担“从底部抬升”的职责**
   - 欢迎语、输入框、todo 区块仍在同一内容列中
   - 但位置由文档流决定，而不是绝对定位和 transform

4. **宿主恢复显示时增加显式 viewport 恢复信号**
   - EHM 当前对 AI 工作台 iframe 使用缓存与 `v-show` 显示/隐藏
   - DeerFlow 子页不会从 `document.visibilitychange` 得知这种隐藏/恢复
   - 因此宿主在以下时机主动向 iframe 发送一条恢复消息：
     - iframe 首次 `load` 完成后
     - AI 工作台 tab 重新显示后
   - 该消息只表达“请按当前容器尺寸重排”，不承载业务状态

5. **DeerFlow 收到恢复消息后统一触发 reflow**
   - DeerFlow host bridge 将宿主消息转成本地事件
   - 聊天页收到事件后执行一次轻量 reflow：
     - `window.dispatchEvent(new Event("resize"))`
     - 递增本地 `layoutEpoch`，让首屏 / streaming 敏感容器按最新尺寸重新挂载
   - 这样问题不再依赖首次 mount 时的偶然容器尺寸

6. **普通会话页保持原布局**
   - 减少回归范围
   - 避免把修复范围扩大到历史会话滚动和输入区遮挡逻辑

## Risks / Trade-offs

- 新对话首屏的视觉位置会与当前实现略有差异，但这是可接受的，因为目标是稳定性优先。
- 若某些依赖当前绝对定位的装饰元素与新布局冲突，需要同步微调边距。
- 新增宿主恢复事件意味着 EHM 与 DeerFlow 之间增加一条轻量消息协议，需要两端同步升级。

## Verification

- 登录后首次进入 AI 工作台，首屏输入区应保持正常宽度
- 浏览器刷新后首次进入 AI 工作台，首屏输入区应保持正常宽度
- 在首个新对话开始 streaming 且仍为首轮初始化时切走再切回，不应出现输入区压窄或整体错位
- 进入历史对话与再次新建对话，普通会话布局保持不变
- 宿主重新显示 AI 工作台 tab 后，DeerFlow 应收到恢复消息并按当前容器尺寸重排
