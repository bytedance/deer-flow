# 中间件系统 (Middleware Chain)

Lead-agent 中间件按严格顺序组装，分布在两个位置：
- `packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py` (`build_lead_runtime_middlewares`)
- `packages/harness/deerflow/agents/lead_agent/agent.py` (`_build_middlewares`)

## 中间件执行顺序

```
请求 → [1-3 准备] → [4-8 错误处理] → [9-11 可选功能] → [12-15 后处理] → [16-18 收尾] → 响应
```

## 中间件详解

### 1. ThreadDataMiddleware
**职责**: 创建每线程隔离目录
- 在用户隔离作用域下创建 `backend/.deer-flow/users/{user_id}/threads/{thread_id}/user-data/{workspace,uploads,outputs}`
- 通过 `get_effective_user_id()` 解析 `user_id`（无认证模式回退到 `"default"`）
- Web UI 线程删除时，Gateway 清理本地线程目录

### 2. UploadsMiddleware
**职责**: 追踪并注入新上传文件到对话中

### 3. SandboxMiddleware
**职责**: 获取沙箱，将 `sandbox_id` 存储到状态

### 4. DanglingToolCallMiddleware
**职责**: 为缺少响应的 AIMessage tool_calls 注入占位 ToolMessage
- 处理用户中断等场景
- 保留原始 provider tool-call payload 在 `additional_kwargs["tool_calls"]`

### 5. LLMErrorHandlingMiddleware
**职责**: 标准化 provider/model 调用失败
- 将错误转换为可恢复的 assistant-facing 错误
- 在后续中间件/工具阶段之前处理

### 6. GuardrailMiddleware (可选)
**职责**: 工具调用前的授权检查
- 条件: `guardrails.enabled` in config
- 通过可插拔的 `GuardrailProvider` 协议评估每个工具调用
- 拒绝时返回错误 ToolMessage
- 三种 provider: 内置 `AllowlistProvider`、OAP 策略 provider、自定义 provider
- 详见 [GUARDRAILS.md](GUARDRAILS.md)

### 7. SandboxAuditMiddleware
**职责**: 审计沙箱 shell/文件操作
- 在工具执行前进行安全日志记录

### 8. ToolErrorHandlingMiddleware
**职责**: 工具异常转换
- 将工具异常转换为错误 `ToolMessage`
- 允许运行继续而非中断

### 9. SummarizationMiddleware (可选)
**职责**: 上下文压缩
- 条件: config 中启用
- 接近 token 限制时触发

### 10. TodoListMiddleware (可选)
**职责**: 任务追踪
- 条件: `is_plan_mode = True`
- 提供 `write_todos` 工具

### 11. TokenUsageMiddleware (可选)
**职责**: 记录 token 使用指标
- 条件: 启用 token 追踪

### 12. TitleMiddleware
**职责**: 自动生成线程标题
- 在第一次完整对话后触发
- 标准化结构化消息内容后再提示标题模型

### 13. MemoryMiddleware
**职责**: 异步记忆更新队列
- 过滤消息（仅保留用户输入 + 最终 AI 响应）
- 捕获 `user_id` 以在定时器线程边界后保留

### 14. ViewImageMiddleware
**职责**: 注入 base64 图片数据
- 条件: 模型支持视觉
- 在 LLM 调用前处理

### 15. DeferredToolFilterMiddleware (可选)
**职责**: 隐藏延迟工具的 schema
- 直到工具搜索启用

### 16. SubagentLimitMiddleware (可选)
**职责**: 截断过多的 `task` 工具调用
- 条件: `subagent_enabled`
- 强制执行 `MAX_CONCURRENT_SUBAGENTS` 限制

### 17. LoopDetectionMiddleware
**职责**: 检测重复工具调用循环
- 硬停止响应清除结构化 `tool_calls` 和原始 provider 元数据
- 强制输出最终文本答案

### 18. ClarificationMiddleware (必须最后)
**职责**: 拦截 `ask_clarification` 工具调用
- 通过 `Command(goto=END)` 中断
- 必须是中间件链的最后一个

## 中间件交互图

```
┌─────────────────────────────────────────────────────────────────┐
│                      准备阶段 (1-3)                              │
│  ThreadData → Uploads → Sandbox                                 │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                    错误处理阶段 (4-8)                            │
│  DanglingToolCall → LLMError → Guardrail? → SandboxAudit       │
│  → ToolError                                                    │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                    可选功能阶段 (9-11)                           │
│  Summarization? → TodoList? → TokenUsage?                       │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                    后处理阶段 (12-15)                            │
│  Title → Memory → ViewImage → DeferredToolFilter?               │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                      收尾阶段 (16-18)                            │
│  SubagentLimit? → LoopDetection → Clarification (必须最后)       │
└─────────────────────────────────────────────────────────────────┘
```

## 配置选项

| 中间件 | 配置项 | 默认值 |
|--------|--------|--------|
| GuardrailMiddleware | `guardrails.enabled` | false |
| SummarizationMiddleware | `summarization.enabled` | false |
| TodoListMiddleware | `config.configurable.is_plan_mode` | false |
| TokenUsageMiddleware | token tracking enabled | false |
| SubagentLimitMiddleware | `subagent_enabled` | false |

## 扩展指南

添加新中间件时：
1. 确定插入位置（准备/错误处理/可选/后处理/收尾）
2. 在 `build_lead_runtime_middlewares` 或 `_build_middlewares` 中添加
3. 注意顺序依赖（如 ClarificationMiddleware 必须最后）
4. 添加对应的配置开关（如果是可选功能）
5. 编写单元测试验证行为
