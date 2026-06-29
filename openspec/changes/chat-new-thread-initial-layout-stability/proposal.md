## Why

EHM 通过 iframe 打开 DeerFlow AI 工作台时，聊天页的新对话首屏在首次进入阶段存在不稳定布局。当前 `/workspace/chats/new` 使用一套与普通会话页不同的“视觉居中”布局，并依赖绝对定位与大幅 `translateY` 偏移来把输入框抬到页面中部。

在以下场景中，这套布局会稳定或高概率地出现错误尺寸：

- 浏览器刷新后第一次进入 AI 工作台
- 退出登录后重新登录，再次进入 AI 工作台
- 新对话首屏还未完成首次发送 / 首次 streaming 时，宿主切走 iframe 再切回

用户看到的表现包括：

- 输入框被压成极窄竖条
- 欢迎首屏与输入区域横向错位
- 左右区块宽度异常，且进入历史对话后恢复正常

这说明问题集中在“新对话首屏初始化布局”，而不是普通历史会话或稳定态聊天页面。

## What Changes

- 移除新对话首屏对 `translateY(calc(50vh-96px))` 的依赖
- 将新对话首屏输入区改为正常文档流 / flex 布局，而不是底部绝对定位容器中的强制位移
- 在 EHM 宿主重新显示 AI 工作台 iframe 或首次 load 完成后，宿主向 DeerFlow 发送一个 viewport 恢复事件
- DeerFlow 在收到宿主恢复事件后，触发一次统一的聊天页 reflow / resize，覆盖登录后首次进入、刷新后首次进入、首轮 streaming 切换等场景
- 保持普通历史会话页现有底部 dock 布局不变

## Capabilities

### Modified Capabilities

- `workspace-chat-layout`: 新对话首屏在 iframe 冷启动、登录后首次进入和首轮 streaming 切换期间保持稳定宽度与位置

## Impact

- Frontend chat page layout
- Frontend EHM host bridge event handling
- EHM host iframe visibility resume signaling
- Frontend new-thread composer positioning
- Frontend chat page verification for EHM iframe entry behavior
