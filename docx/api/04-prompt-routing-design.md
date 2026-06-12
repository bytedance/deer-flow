# DeerFlow 快捷入口提示词路由设计文档

## 1. 背景与目标

在前端新增四类快捷入口，用户点击后自动填充对应的提示词，DeerFlow 通过提示词识别用户意图并路由到对应的 Skill 或 Dify Workflow Tool。

### 新增快捷入口

| 入口名称 | 路由目标 | 调用方式 |
|----------|----------|----------|
| 数据分析 | `data-analysis` skill | Skill |
| AI写作 | AI写作 Dify Workflow | Dify Tool |
| 文档检验 | 文档校验 Dify Workflow | Dify Tool |
| 图片识别 | 图片识别 Dify Workflow | Dify Tool |

---

## 2. 当前 DeerFlow 路由机制分析

### 2.1 Skill 路由

DeerFlow 的 Skill 系统通过 `SKILL.md` 中定义的 `allowed-tools` 来限定 Skill 可使用的工具，并通过提示词让 Agent 理解何时调用该 Skill。

**Skill 格式：**
```yaml
---
name: skill-name
description: Skill 描述
allowed-tools:
  - read_file
  - write_file
  - bash
---
# Skill 指令内容
```

### 2.2 Dify Workflow Tool 路由

Dify Workflow 通过 `dify_workflow` 工具暴露给 Agent。工具调用时需要传递 `workflow_name` 参数来指定调用哪个工作流。

**Dify Tool 调用方式：**
```json
{
  "tool_call": "dify_workflow",
  "input": {
    "workflow_name": "ai-writing",    // AI写作
    "workflow_name": "doc-verify",    // 文档校验
    "workflow_name": "image-ocr",     // 图片识别
    "workflow_name": "data-analysis"  // 数据分析（如有）
  }
}
```

### 2.3 当前快捷提示词结构

参考现有 `suggestions` 配置：

```typescript
suggestions: [
  {
    suggestion: "写作",
    prompt: "撰写一篇关于[主题]的博客文章",
    icon: PenLineIcon,
  },
  {
    suggestion: "研究",
    prompt: "深入浅出的研究一下[主题]，并总结发现。",
    icon: MicroscopeIcon,
  },
]
```

---

## 3. 提示词组织策略

### 3.1 核心原则：明确写出要使用的工具名称

**最简单有效的方式**：在提示词中**直接、明确**写出要使用的技能或工作流名称，让 Agent 自然理解并调用。

```
"请使用数据分析技能，帮我分析：..."
"请使用AI写作工作流，帮我写：..."
"请使用文档校验工作流，帮我校验：..."
"请使用图片识别工作流，帮我识别：..."
```

**不需要特殊前缀、不需要 metadata、前端后端都不需要改**，只需在提示词中写清楚即可。

---

## 4. 推荐方案：直接明确写法

### 方案说明

**核心思路**：在提示词中直接、明确地说明要使用的工具/技能名称。

| 入口 | 提示词格式 | Agent 行为 |
|------|-----------|------------|
| 数据分析 | `请使用数据分析技能，帮我分析：[主题]` | 调用 `data-analysis` skill |
| AI写作 | `请使用AI写作工作流，帮我写：[主题]` | 调用 `dify_workflow(workflow_name="ai-writing")` |
| 文档检验 | `请使用文档校验工作流，帮我校验：[主题]` | 调用 `dify_workflow(workflow_name="doc-verify")` |
| 图片识别 | `请使用图片识别工作流，帮我识别：[主题]` | 调用 `dify_workflow(workflow_name="image-ocr")` |

### 为什么这样有效

1. **DeerFlow Agent 已有 `dify_workflow` 工具**，工具描述会说明需要 `workflow_name` 参数
2. **data-analysis skill 已在 `allowed-tools` 中配置**，Agent 理解何时使用
3. **提示词中明确写出工具名称**，Agent 自然会按提示执行

---

## 5. 具体提示词模板

**说明**：`[用户输入]` 是一个占位符，发送时会被替换为用户在输入框中的实际内容。

### 5.1 数据分析（Skill 路由）

**要求**：第一轮回复仅做简单分析，后续可根据用户需求深入。

```typescript
{
  suggestion: "数据分析",
  prompt: "请使用数据分析技能，对数据做一个快速的初步分析，给出关键发现和简要结论。如果需要更深入的分析，我会告诉你具体想深入的方向。\n\n用户需求：[用户输入]",
  icon: ChartBarIcon,
  description: "数据分析与可视化（初步分析）"
}
```

### 5.2 AI写作（Dify Workflow 路由）

```typescript
{
  suggestion: "AI写作",
  prompt: "请使用AI写作工作流，帮助我完成以下写作任务：\n[用户输入]",
  icon: PenToolIcon,
  description: "AI智能写作助手"
}
```

### 5.3 文档检验（Dify Workflow 路由）

```typescript
{
  suggestion: "文档检验",
  prompt: "请使用文档校验工作流，检验以下文档：\n[用户输入]",
  icon: FileCheckIcon,
  description: "文档质量检验"
}
```

### 5.4 图片识别（Dify Workflow 路由）

```typescript
{
  suggestion: "图片识别",
  prompt: "请使用图片识别工作流，识别图片内容：\n[用户输入]",
  icon: ScanIcon,
  description: "图片内容识别"
}
```

---

## 6. 前端实现示例

### 6.1 i18n 配置扩展

```typescript
// zh-CN.ts
{
  quickActions: {
    dataAnalysis: {
      suggestion: "数据分析",
      prompt: "请使用数据分析技能，帮助我分析以下数据：[主题]",
      icon: "ChartBar",
    },
    aiWriting: {
      suggestion: "AI写作",
      prompt: "请使用AI写作工作流，帮助我完成以下写作任务：[主题]",
      icon: "PenTool",
    },
    docVerify: {
      suggestion: "文档检验",
      prompt: "请使用文档校验工作流，检验以下文档：[主题]",
      icon: "FileCheck",
    },
    imageOcr: {
      suggestion: "图片识别",
      prompt: "请使用图片识别工作流，识别图片内容：[主题]",
      icon: "Scan",
    },
  }
}
```

### 6.2 前端组件实现

**关键设计**：点击快捷入口**不改变输入框显示**，而是在发送时组合完整提示词。

```tsx
// input-box.tsx
const quickActions = [
  {
    key: 'dataAnalysis',
    label: t.quickActions.dataAnalysis.suggestion,
    icon: ChartBarIcon,
    promptTemplate: t.quickActions.dataAnalysis.prompt,
  },
  // ... 其他入口
];

// 点击快捷入口时：输入框显示不变，实际发送组合后的提示词
const handleQuickAction = (action: typeof quickActions[0]) => {
  const userInput = inputRef.current.value; // 获取用户已输入内容

  // 组合完整提示词
  const fullPrompt = action.promptTemplate.replace(
    '[用户输入]',
    userInput.trim() || '[请输入您的需求]'
  );

  // 直接发送，不改变输入框显示
  sendMessage(fullPrompt);
};

// 普通的输入框输入行为不变
const handleInputChange = (e) => {
  setInputValue(e.target.value); // 输入框显示用户输入的内容
};
```

### 6.3 发送流程对比

```
┌─────────────────────────────────────────────────────────────┐
│  普通发送流程                                                │
├─────────────────────────────────────────────────────────────┤
│  用户输入框显示："我想写一篇博客"                             │
│  点击发送                                                    │
│  实际发送："我想写一篇博客"                                  │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  快捷入口发送流程                                            │
├─────────────────────────────────────────────────────────────┤
│  用户输入框显示："我想写一篇关于AI的博客"                     │
│  点击"AI写作"快捷入口                                       │
│  输入框显示不变（仍为"我想写一篇关于AI的博客"）               │
│  实际发送："请使用AI写作工作流，帮助我完成以下写作任务：\n    │
│           我想写一篇关于AI的博客"                            │
└─────────────────────────────────────────────────────────────┘
```

---

## 7. 后端 Skill/Tool 配置要求

### 7.1 data-analysis Skill 配置

确保 `data-analysis` skill 的 `SKILL.md` 包含：

```yaml
---
name: data-analysis
description: 专业数据分析技能，支持数据清洗、统计分析、可视化和报告生成
allowed-tools:
  - read_file
  - write_file
  - bash
  - python
---
# Skill 指令
你是一个专业的数据分析师。当用户请求数据分析时：
1. 首先理解用户的数据和分析需求
2. 使用 read_file 读取数据文件
3. 使用 bash 或 python 进行数据处理和分析
4. 使用 write_file 生成分析报告
5. 生成可视化图表（如需要）
```

### 7.2 Dify Workflow Tool 配置

确保 Dify Tool 在 `config.yaml` 中正确配置：

```yaml
tools:
  - name: dify_workflow
    use: deerflow.community.dify.tools:dify_workflow
    group: community
```

---

## 8. 验证测试用例

### 8.1 数据分析测试

```
用户输入：帮我分析这份销售数据
期望路由：data-analysis skill
验证点：
- [ ] Agent 调用 data-analysis skill
- [ ] 使用 read_file 读取数据
- [ ] 生成分析报告
```

### 8.2 AI写作测试

```
用户输入：请帮我写一篇关于AI的文章
期望路由：dify_workflow (ai-writing)
验证点：
- [ ] Agent 调用 dify_workflow
- [ ] workflow_name = "ai-writing"
```

### 8.3 文档校验测试

```
用户输入：帮我校验这份文档
期望路由：dify_workflow (doc-verify)
验证点：
- [ ] Agent 调用 dify_workflow
- [ ] workflow_name = "doc-verify"
```

### 8.4 图片识别测试

```
用户输入：识别这张图片的内容
期望路由：dify_workflow (image-ocr)
验证点：
- [ ] Agent 调用 dify_workflow
- [ ] workflow_name = "image-ocr"
```

---

## 9. 待确认事项

~~1. **Dify 工作流名称**：需要确认 AI写作、文档校验、图片识别 的 Dify workflow 实际名称~~ ✅ 已确认
~~2. **data-analysis skill**：确认是否已安装或需要安装~~ ✅ 已确认可用
3. **数据分析第一轮要求**：用户要求第一轮仅做简单分析，文档已更新
4. **用户输入位置**：`[用户输入]` 是用户点击后输入框留空让用户补充，还是替换用户已输入的内容？
5. **快捷入口位置**：这些入口是放在首页（landing）还是聊天页面（input-box）？
