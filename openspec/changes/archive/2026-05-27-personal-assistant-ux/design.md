## Context

DeerFlow 当前以 "EHM AI 工作台" 身份运行，system prompt 定义了一个功能导向的 super agent。用户打开新对话时看到的是空白聊天界面和"No messages yet"提示。系统回应以技术中立语气为主，错误信息直接暴露技术细节（HTTP 状态码、异常栈）。任务完成后对话即终止，没有后续跟进。

现有基础设施已具备支撑"助理感"的能力：
- **Memory System**：存储 userContext、recentMonths、longTermBackground 等用户画像
- **TitleMiddleware**：已有首轮交互后的标题生成
- **ClarificationMiddleware**：已有澄清提问机制
- **GenUI**：可推送卡片、表单等富交互
- **Suggestions API**：已有 follow-up 建议生成

## Goals / Non-Goals

**Goals:**
- 用户从第一次打开对话就感受到"被认识、被关心"的助理体验
- 助理在所有场景（回答、错误、等待、完成）中保持一致的温暖专业语气
- 系统主动推送有价值的建议，而不是被动等待用户发起请求
- 任务完成后形成闭环（总结 → 询问后续 → 下次跟进）

**Non-Goals:**
- 不引入虚拟形象/动画角色（避免增加认知负担）
- 不改变现有 agent 架构或 middleware 链顺序
- 不引入新的 LLM 模型调用（复用现有模型，通过 prompt 和 hook 实现）
- 不修改 Memory System 的数据结构（只消费已有数据）

## Decisions

### D1: 助理人格通过 system prompt 增强实现，不引入新的 SOUL.md

**选择**：在 `SYSTEM_PROMPT_TEMPLATE` 中新增 `<assistant_persona>` section，定义语气规则、共情表达模板、主动关怀行为。

**理由**：
- SOUL.md 是 per-agent 的，而助理人格应该是跨 agent 的基线行为
- system prompt 增强确保所有 agent（builtin/tenant/user）自动继承
- 不增加文件 I/O 或新的加载逻辑

**替代方案**：为每个 agent 添加 persona 字段到 AgentConfig → 需要 schema migration 和 CRUD 改动，ROI 过低

### D2: 主动问候通过前端 empty state 组件 + 后端 greeting API 实现

**选择**：
1. 新增 `GET /api/threads/{thread_id}/greeting` API，基于 memory context 和近期工作状态生成个性化问候
2. 前端 `ConversationEmptyState` 组件在首次渲染时调用 greeting API，展示问候卡片和建议操作

**理由**：
- 复用现有 memory 数据，不需要新数据源
- greeting 作为 API 而非 middleware，不干扰正常对话流
- 前端可渐进展示：先显示骨架屏，API 返回后替换为个性化内容

**替代方案**：在 agent 首轮响应前注入 greeting message → 会导致 LangGraph state 中出现非用户发起的 message，破坏 thread 的消息一致性

### D3: 共情错误处理通过 LLMErrorHandlingMiddleware 增强 + 前端 i18n 兜底

**选择**：
1. 后端 `LLMErrorHandlingMiddleware` 中，将技术错误映射为错误类别枚举（`network_issue`、`timeout`、`service_unavailable`、`data_not_found`）
2. 前端 i18n 为每个错误类别定义温暖的双语文案
3. 错误响应中附带建议的下一步操作（"重试"、"换个时间范围"、"联系客服"）

**理由**：
- 后端不需要 LLM 调用来生成错误文案（确定性映射，低延迟）
- 前端 i18n 保证双语支持和快速迭代
- 保持现有 middleware 链不变

### D4: 关怀闭环通过 post-completion hook 实现

**选择**：
1. 在 `TitleMiddleware` 之后添加轻量 `CareLoopMiddleware`（仅当 thread 有分析报告产出时激活）
2. Middleware 在 assistant 最终回复末尾追加 follow-up 提示模板（"需要我帮您继续看看 X 吗？"）
3. 在 memory facts 中记录 `pendingFollowUp` 标记，下次对话时触发问候 API 引用

**理由**：
- 复用现有 middleware 机制，不引入新概念
- follow-up 提示由 LLM 自然生成（通过 prompt 引导），不硬编码文案
- memory 中标记 follow-up，跨 session 保持连续性

**替代方案**：独立的 follow-up notification 系统 → 需要通知基础设施，远超当前 scope

### D5: 前端助理形象通过轻量 UI 增强实现

**选择**：
1. 为 assistant 消息添加头像（使用 agent icon）和 "助理" 标签
2. 流式响应时显示状态指示（"正在思考…"、"正在查询数据…"、"正在生成报告…"）——从 tool call 名称推导
3. 问候卡片组件：圆形头像 + 问候文案 + 2-3 个建议操作 chips

**理由**：
- 改动量小，利用现有 agent config 中的 `icon` 字段
- 状态指示从 stream events 推导，不需要后端改动
- 问候卡片可复用 Shadcn Card 组件

### D6: 工业场景的助理行为约束

**选择**：助理在工业场景（设备监控、故障诊断、闭环工单）中遵循安全优先原则：

1. **安全语气分级**：系统 prompt 中定义四级语气（正常/注意/警告/紧急），severity ≥ warning 时自动切换直接紧迫语气，禁止软化语言
2. **告警感知问候**：Greeting API 在生成问候前查询用户监控设备的活跃告警，有告警时优先推送告警而非闲聊
3. **设备优先级排序**：建议 chips 按设备关键度（关键 > 重要 > 一般）排序，近期异常自动提升排序权重
4. **闭环工单跟进**：Greeting API 和 follow-up 提示主动引用用户相关的开放工单状态变化和近期关闭工单的复检需求
5. **预防性维护提醒**：设备元数据中包含计划检修日期时，问候主动推送维护提醒（14天内）并提议生成状态评估报告

**理由**：

- 工业场景的安全要求高于通用场景，语气必须与严重度匹配
- 闭环工单和预防性维护是工业用户的核心工作流，助理跟进这些能显著提升实用性
- 所有数据源（告警、工单、设备元数据、维护计划）已在系统中存在，无需新集成

**替代方案**：接入外部 MES/ERP 排班系统 → 当前现场无电子排班数据，排除。未来可通过 HTTP connector 按需接入。

### D7: 语言跟随用户输入

**选择**：助理响应语言跟随用户最近一条消息的语言。实现方式分两层：

1. **System prompt 层**：persona section 加入 "match the user's language" 指令，LLM 自动跟随
2. **Greeting API 层**：检测 thread 中用户最后一条消息的语言（简单 Unicode 范围判断：CJK → zh-CN，Latin → en-US），生成对应语言的问候和建议；新 thread 无消息时默认 zh-CN

**理由**：
- 不需要前端传 locale 参数，减少集成复杂度
- LLM 本身就有语言跟随能力，prompt 一行指令即可
- greeting 是后端生成的动态内容，需要在 API 层做语言判断

**替代方案**：完整 locale 系统（前端 i18n + 后端 locale header）→ 当前只有中英双语需求，ROI 不足

## Risks / Trade-offs

**[Risk] Greeting API 增加首次加载延迟** → Mitigation: 前端先渲染通用问候骨架屏，API 返回后替换。设置 2s 超时，超时则显示默认问候。告警和设备元数据查询并行化，控制在 1s 内。

**[Risk] 助理人格 prompt 增长影响 token 成本** → Mitigation: persona section 控制在 400 tokens 以内（含安全语气分级）。使用简洁的规则描述而非大量示例。

**[Risk] 主动建议可能不准确或打扰用户** → Mitigation: 建议仅在置信度高时推送（有明确的 memory 或数据支撑）。提供"不再显示建议"的 dismiss 选项。

**[Risk] 共情错误文案可能与实际错误不匹配** → Mitigation: 使用宽泛的错误类别而非具体描述。保留"查看详情"链接展示原始技术信息。

**[Risk] 告警数据延迟或缺失导致问候不感知告警** → Mitigation: Greeting API 的告警查询设置 500ms 超时，超时则跳过告警检查，使用普通问候流程。不阻塞问候渲染。

**[Risk] 闭环工单跟进可能重复推送已处理工单** → Mitigation: 仅推送状态变化（新建→处理中→关闭）和 7 天内关闭的工单。30 天前的工单不再主动推送。

**[Trade-off] 不引入虚拟形象**：牺牲了一些"人格化"感知，但避免了加载性能、设计维护、以及部分用户对卡通形象的反感。

**[Trade-off] 班次感知暂不实现**：当前现场无电子排班数据，班次感知（"您刚接班，要不要看看夜班情况"）暂不实现。未来接入排班系统后可通过 HTTP connector 扩展。
