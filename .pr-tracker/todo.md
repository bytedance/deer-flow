# Contribution Todo List

> 按优先级排序，标记预估工作量和成功概率
> 筛选优先级: 🤝Sub-agent > 🛠️Skill > 🧩Context Engineering > 💾Memory > 🏗️Sandbox

## 🔥 High Priority (高潜力)

### [Issue #4492] 子智能体执行问题：数据库事件循环冲突 & 工具列表被 skill的allowed-tools 策略过度裁剪
- **预估工作量**: 4-8h
- **成功概率**: ⭐⭐⭐⭐
- **优先级匹配**: #1 Sub-agent + #2 Skill
- **理由**: P1 级 bug，涉及子智能体执行的核心问题（DB 事件循环冲突 + Skill 工具裁剪），与我的专长方向高度匹配。有 maintainer (AnnaSuSu) 关注，但尚无明确修复 PR。
- **相关文件**: backend/ 下的 sub-agent 执行器、skill 管理器
- **状态**: 🟡 分析中

### [Issue #4529] Allow users to bypass ask_clarification form by typing in chat input
- **预估工作量**: 2-3h
- **成功概率**: ⭐⭐⭐⭐⭐
- **优先级匹配**: #3 Context Engineering
- **理由**: 小而明确的功能改进，允许用户在 ask_clarification 表单期间直接在聊天输入框输入以绕过表单。无 `needs-triage` 之外的标签，需自行理解实现。
- **相关文件**: ClarificationMiddleware, frontend clarification 组件
- **状态**: 🟡 分析中

### [Issue #4526] ask_clarification options rendered as raw dict string when model outputs XML-style options
- **预估工作量**: 2-3h
- **成功概率**: ⭐⭐⭐⭐⭐
- **优先级匹配**: #3 Context Engineering
- **理由**: 明确的 bug 修复，当模型输出 XML 风格选项时，ask_clarification 选项被渲染为原始 dict 字符串。已有 PR #4527 修复类似问题，可参考。
- **相关文件**: backend clarification 相关代码
- **状态**: 🟡 分析中

### [Issue #4416] [Security][MCP] Prevent per-request credentials in run metadata from being persisted or exposed
- **预估工作量**: 1-2d
- **成功概率**: ⭐⭐⭐
- **优先级匹配**: #5 Sandbox/Dev
- **理由**: 有 `help wanted` 标签，有详细的实现讨论。但涉及安全敏感区域，需要谨慎处理。已有贡献者 (ShitK) 认领，需确认是否仍需帮助。
- **相关文件**: secret_context, run admission boundary
- **状态**: ⚪ 待开始

## 🔵 Medium Priority (中等潜力)

### [Issue #4495] [feat] relevance-aware fact retrieval for DeerMem
- **预估工作量**: 1-2d
- **成功概率**: ⭐⭐⭐
- **优先级匹配**: #4 Memory
- **理由**: Memory 增强功能，与研究方向匹配。Enhancement 类型，无明确实现细节。
- **相关文件**: memory/ 相关模块
- **状态**: ⚪ 待开始

### [Issue #4481] [bug] Default backend test command runs live LLM integration tests without explicit opt-in
- **预估工作量**: 3-4h
- **成功概率**: ⭐⭐⭐⭐⭐
- **优先级匹配**: #5 Sandbox/Dev
- **理由**: 测试基础设施改进，明确且低风险。已有 PR #4502 和 #4483 处理类似问题。
- **相关文件**: Makefile, backend test config
- **状态**: ⚪ 待开始

### [Issue #4404] [bug] Corepack-only 环境中 make check 通过，但安装和启动命令找不到 pnpm
- **预估工作量**: 2-4h
- **成功概率**: ⭐⭐⭐⭐⭐
- **优先级匹配**: #5 Sandbox/Dev
- **理由**: 构建环境修复，已有 PR #4507, #4474, #4405 处理相关问题。
- **相关文件**: Makefile, build scripts
- **状态**: ⚪ 待开始

## ❌ Rejected (排除项)

### [Issue #4531] 编辑并重跑功能在单轮对话中不生效
- **原因**: 已有修复 PR #4534 (由 AnnaSuSu 提交)

### [Issue #4522] 中断对话重新生成提示
- **原因**: 已有修复 PR #4524 (由 AnnaSuSu 提交)

### [Issue #4514] reasoning_effort 字段不匹配异常
- **原因**: 已有修复 PR #4515 (由 Void615 提交)

### [Issue #4424] Orphan reconciliation
- **原因**: 已有人认领并报告修复完成

### [Issue #4400] A2UI-style declarative HITL cards
- **原因**: 大型 RFC，已有 PR #4406，工作量过大且涉及架构争议

### [Issue #4409] 长任务流式渲染性能
- **原因**: 复杂性能优化，需要深入的前端性能分析，且已有多个 PR 处理

### [Issue #4496] Security Report
- **原因**: 外部安全报告，需要特殊处理流程

### [Issue #4462] 前端依赖优化
- **原因**: 社区已给出详细解决方案 (使用 make start)，非代码问题
