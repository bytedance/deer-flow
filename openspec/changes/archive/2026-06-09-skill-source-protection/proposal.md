## Why

Skill 脚本（/mnt/skills/ 下的 .py 文件）和 SKILL.md 指令包含核心业务逻辑、数据处理算法和系统架构细节。当前系统仅保护了写权限（skills 路径 read-only），但 Agent 可以通过 `read_file`、`bash`（cat/head 等）工具读取脚本源码并展示给用户。这意味着：

1. **知识产权泄露风险**：用户可以要求 Agent 展示 skill 脚本内容，获取完整的数据查询逻辑、KPI 计算公式、报告生成算法
2. **系统提示提取风险**：SKILL.md 完整内容注入到 Agent 的 System Prompt 中，通过 prompt injection 攻击可能提取出 Skill 指令和脚本路径
3. **竞争情报暴露**：故障诊断规则、设备数据模型、异常检测算法等属于核心商业逻辑

需要立即实施多层防护，防止 Skill 源码和指令被未授权访问。

## What Changes

- **Prompt 层防护**：在所有 Agent 的 SOUL.md 和系统提示中添加安全红线，禁止向用户展示 Skill 脚本源码
- **工具层拦截**：在 `read_file`、`bash`、`ls` 工具中增加 skill 源码读取检测，拦截对 `/mnt/skills/**/*.py` 的直接访问
- **沙箱审计增强**：`SandboxAuditMiddleware` 增加 skill 源码读取规则，将此类命令标记为 `block`
- **Prompt 注入优化**（可选，Phase 2）：减少 SKILL.md 完整内容注入，改为仅注入元数据（name + description），具体指令按需加载

## Capabilities

### New Capabilities
- `skill-source-protection`: Skill 脚本源码和指令的访问控制与防护机制，涵盖 prompt 禁令、工具拦截、沙箱审计

### Modified Capabilities

无现有 spec 的需求变更。现有 skill 相关 spec（daily-report-skill、weekly-report-skill 等）描述的是 skill 功能，不涉及保护机制。

## Impact

**受影响代码**：
- `backend/packages/harness/deerflow/sandbox/tools.py` — read_file、bash、ls 工具增加 skill 源码检测
- `backend/packages/harness/deerflow/agents/middlewares/sandbox_audit_middleware.py` — 增加 skill 源码读取拦截规则
- `backend/packages/harness/deerflow/agents/lead_agent/prompt.py` — 系统提示生成时注入安全指令（Phase 1）
- `agents/builtin/*/SOUL.md` — 各 Agent SOUL 文件添加安全红线（Phase 1）
- `backend/tests/` — 新增测试覆盖 skill 源码保护场景

**API/依赖**：无外部 API 变更，无新增依赖

**系统行为变化**：
- Agent 尝试读取 skill 脚本时会收到拒绝消息，用户看到"访问被拒绝"而非脚本内容
- SOUL.md 增加安全约束，Agent 主动拒绝用户的源码查看请求
- （Phase 2）System Prompt 中 skill 内容减少，可能影响 Agent 对 skill 用法的理解深度

**风险**：
- Phase 1（prompt + 工具拦截）：低风险，不影响正常 skill 使用
- Phase 2（prompt 注入优化）：中风险，需要验证 Agent 仍能正确调用 skill
