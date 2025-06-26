# 思考块功能 (Thought Block Feature)

## 概述

思考块功能允许在计划卡片之前展示 AI 的深度思考过程，以可折叠的方式呈现推理内容。这个功能特别适用于启用深度思考模式时的场景。

## 功能特性

- **智能展示逻辑**: 深度思考过程初始展开，当开始接收计划内容时自动折叠
- **分阶段显示**: 思考阶段只显示思考块，思考结束后才显示计划卡片
- **流式支持**: 支持推理内容的实时流式展示
- **视觉状态反馈**: 思考阶段使用蓝色主题突出显示
- **优雅的动画**: 包含平滑的展开/折叠动画效果
- **响应式设计**: 适配不同屏幕尺寸

## 技术实现

### 数据结构更新

1. **Message 类型扩展**:
   ```typescript
   export interface Message {
     // ... 其他字段
     reasoningContent?: string;
     reasoningContentChunks?: string[];
   }
   ```

2. **API 事件类型扩展**:
   ```typescript
   export interface MessageChunkEvent {
     // ... 其他字段
     reasoning_content?: string;
   }
   ```

### 组件结构

- **ThoughtBlock**: 主要的思考块组件
  - 使用 Radix UI 的 Collapsible 组件
  - 支持流式内容展示
  - 包含加载动画和状态指示

- **PlanCard**: 更新后的计划卡片
  - 在计划内容之前展示思考块
  - 自动检测是否有推理内容

### 消息处理

消息合并逻辑已更新以支持 `reasoning_content` 字段的流式处理：

```typescript
function mergeTextMessage(message: Message, event: MessageChunkEvent) {
  // 处理常规内容
  if (event.data.content) {
    message.content += event.data.content;
    message.contentChunks.push(event.data.content);
  }
  
  // 处理推理内容
  if (event.data.reasoning_content) {
    message.reasoningContent = (message.reasoningContent || "") + event.data.reasoning_content;
    message.reasoningContentChunks = message.reasoningContentChunks || [];
    message.reasoningContentChunks.push(event.data.reasoning_content);
  }
}
```

## 使用方法

### 启用深度思考模式

1. 在聊天界面中，点击"Deep Thinking"按钮
2. 确保配置了支持推理的模型
3. 发送消息后，如果有推理内容，会在计划卡片上方显示思考块

### 查看推理过程

1. 深度思考开始时，思考块自动展开显示
2. 思考阶段使用 primary 主题色，突出显示正在进行的推理过程
3. 推理内容支持 Markdown 格式渲染，实时流式更新
4. 在流式传输过程中会显示加载动画
5. 当开始接收计划内容时，思考块自动折叠
6. 计划卡片以优雅的动画效果出现
7. 计划内容保持流式输出效果，逐步显示标题、思路和步骤
8. 用户可以随时点击思考块标题栏手动展开/折叠

## 样式特性

- **统一设计语言**: 与页面整体设计风格保持一致
- **字体层次**: 使用与 CardTitle 相同的 `font-semibold` 字体权重
- **圆角设计**: 采用 `rounded-xl` 与其他卡片组件保持一致
- **间距规范**: 使用标准的 `px-6 py-4` 内边距
- **动态主题**: 思考阶段使用 primary 色彩系统
- **图标尺寸**: 18px 图标尺寸，与文字比例协调
- **状态反馈**: 流式传输时显示加载动画和主题色高亮
- **交互反馈**: 标准的 hover 和 focus 状态
- **平滑过渡**: 所有状态变化都有平滑的过渡动画

## 测试数据

可以使用 `/mock/reasoning-example.txt` 文件测试思考块功能，该文件包含了模拟的推理内容和计划数据。

## 兼容性

- 向后兼容：没有推理内容的消息不会显示思考块
- 渐进增强：功能仅在有推理内容时激活
- 优雅降级：如果推理内容为空，组件不会渲染
