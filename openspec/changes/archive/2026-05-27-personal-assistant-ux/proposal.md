## Why

DeerFlow 当前的交互体验偏向"工具"而非"助理"——用户需要主动发起请求、系统以中立技术口吻回应、任务完成后对话即终止。工业用户（设备工程师、运维人员）在日常高频使用中，期望感受到"被关注、被理解、被主动帮助"的温度感。将系统从"冷工具"升级为"有温度的助理"，能显著提升用户粘性、任务完成率和对系统的信任度。

## What Changes

- **助理人格与语气系统**：在 Lead Agent 的 system prompt 中定义助理人格（温暖、专业、主动关心），统一所有输出语气，包括回答、错误提示、加载状态文案
- **主动问候与上下文感知**：新对话开始时，根据用户记忆（memory facts）和近期工作状态生成个性化问候，而非空白等待输入
- **智能建议与主动关怀**：基于设备监控数据异常、即将到期的报告任务、上次未完成的分析等上下文，主动推送建议操作（"您上次分析的泵振动问题，需要我跟进看看趋势吗？"）
- **任务完成后的关怀闭环**：分析/报告完成后，助理主动总结要点、询问是否需要进一步操作、并在后续对话中跟进之前的结论
- **错误场景的共情表达**：将技术性错误信息（"HTTP 500"、"Timeout"）转化为用户可理解的共情表达（"抱歉，数据获取遇到了一些问题，让我换个方式帮您看看"）
- **前端助理形象展示**：在 chat UI 中增加助理头像、状态指示（思考中、正在查数据）、和"助理说"的人格化消息气泡

## Capabilities

### New Capabilities
- `assistant-persona`: 定义助理人格、语气规则、system prompt 模板增强，使所有 AI 输出具备温暖专业的助理风格
- `proactive-greeting`: 新对话/新 session 开始时，基于用户记忆和近期状态生成个性化问候和智能建议
- `empathetic-error-handling`: 将技术错误转化为用户友好的共情表达，包含建议的下一步操作
- `care-loop-followup`: 任务完成后主动总结、询问后续需求、在后续会话中跟进之前的结论

### Modified Capabilities
- `interaction-mode-tiers`: 在 Ultra 自然语言交互基础上增加助理人格语气约束和主动关怀行为

## Impact

- **Backend**：`lead_agent/prompt.py`（system prompt 增强）、`lead_agent/agent.py`（greeting hook）、新增 `proactive_suggestions` 中间件或工具、错误处理中间件增强
- **Frontend**：`chat-box.tsx`（助理头像/状态指示）、新增 greeting 组件、建议卡片组件
- **Memory**：依赖现有 memory system 提供用户上下文（`workContext`、`recentMonths`）来驱动个性化
- **i18n**：需要为共情错误消息和建议文案补充中英文翻译
- **无 Breaking Change**：所有增强为渐进式叠加，不影响现有功能
