# 测试思考块功能

## 快速测试

### 方法 1: 使用模拟数据

1. 在浏览器中访问应用并添加 `?mock=reasoning-example` 参数
2. 发送任意消息
3. 观察计划卡片上方是否出现思考块

### 方法 2: 启用深度思考模式

1. 确保配置了 reasoning 模型（如 DeepSeek R1）
2. 在聊天界面点击"Deep Thinking"按钮
3. 发送一个需要规划的问题
4. 观察是否出现思考块

## 预期行为

### 思考块外观
- 深度思考开始时自动展开显示
- 思考阶段使用 primary 主题色（边框、背景、文字、图标）
- 带有 18px 大脑图标和"深度思考过程"标题
- 使用 `font-semibold` 字体权重，与 CardTitle 保持一致
- `rounded-xl` 圆角设计，与其他卡片组件统一
- 标准的 `px-6 py-4` 内边距

### 交互行为
- 思考阶段：自动展开，蓝色高亮，显示加载动画
- 计划阶段：自动折叠，切换为默认主题
- 用户可随时手动展开/折叠
- 平滑的展开/折叠动画和主题切换

### 分阶段显示
- 思考阶段：只显示思考块，不显示计划卡片
- 计划阶段：思考块折叠，显示完整计划卡片

### 内容渲染
- 支持 Markdown 格式
- 中文内容正确显示
- 保持原有的换行和格式

## 故障排除

### 思考块不显示
1. 检查消息是否包含 `reasoningContent` 字段
2. 确认 `reasoning_content` 事件是否正确处理
3. 验证消息合并逻辑是否正常工作

### 内容显示异常
1. 检查 Markdown 渲染是否正常
2. 确认 CSS 样式是否正确加载
3. 验证动画效果是否启用

### 流式传输问题
1. 检查 WebSocket 连接状态
2. 确认事件流格式是否正确
3. 验证消息更新逻辑

## 开发调试

### 控制台检查
```javascript
// 检查消息对象
const messages = useStore.getState().messages;
const lastMessage = Array.from(messages.values()).pop();
console.log('Reasoning content:', lastMessage?.reasoningContent);
```

### 网络面板
- 查看 SSE 事件流
- 确认 `reasoning_content` 字段存在
- 检查事件格式是否正确

### React DevTools
- 检查 ThoughtBlock 组件状态
- 验证 props 传递是否正确
- 观察组件重新渲染情况
