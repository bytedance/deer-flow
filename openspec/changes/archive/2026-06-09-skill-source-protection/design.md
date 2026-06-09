## Context

DeerFlow 的 Skill 系统允许 Agent 通过沙箱工具（bash、read_file、ls）访问 `/mnt/skills/` 下的脚本和指令文件。当前架构：

**现有保护**：
- 沙箱层面：skills 路径强制 read_only（[tools.py:614-617](backend/packages/harness/deerflow/sandbox/tools.py#L614-L617)）
- bash 审计：[SandboxAuditMiddleware](backend/packages/harness/deerflow/agents/middlewares/sandbox_audit_middleware.py) 拦截危险命令
- 路径脱敏：`mask_local_paths_in_output()` 隐藏宿主机真实路径

**缺失保护**：
- `read_file` / `bash cat` 可以合法读取 `/mnt/skills/**/*.py`
- SOUL.md 和系统提示无禁止展示源码的指令
- SKILL.md 完整内容注入 System Prompt，可被 prompt injection 提取

**约束**：
- Agent 仍需正常调用 skill 脚本（如 `python /mnt/skills/custom/daily-report/scripts/query_daily.py`）
- 保护不应影响正常的 skill 执行流程
- 需考虑 Phase 2 的 prompt 注入优化对 Agent 行为的影响

## Goals / Non-Goals

**Goals:**
- 阻止用户通过 Agent 查看 skill 脚本源码（.py 文件内容）
- 阻止用户通过 Agent 查看 SKILL.md 完整指令内容
- 提供多层防护（prompt 指令 + 工具拦截 + 沙箱审计）
- 保持 Agent 正常调用 skill 脚本的能力不受影响

**Non-Goals:**
- 不改变 skill 脚本的执行方式或文件结构
- 不在 Phase 1 修改 SKILL.md 的 prompt 注入机制（Phase 2 考虑）
- 不实现 skill 内容的细粒度权限控制（如按角色/租户）
- 不加密或混淆 skill 脚本文件

## Decisions

### 决策 1：多层防护策略

**选择**：实施 3 层防护（prompt → 工具 → 沙箱审计）

**理由**：
- **Prompt 层**：第一道防线，教育 Agent 主动拒绝。成本低，见效快，但 LLM 可被绕过
- **工具层**：硬拦截，`read_file` / `bash` 检测 skill 源码路径并拒绝。可靠性高
- **沙箱审计层**：兜底，即使工具层被绕过，审计中间件也能拦截

**替代方案**：
- 仅用 prompt 指令：不够可靠，LLM 可能违反指令
- 仅用工具拦截：缺少用户友好的拒绝消息，用户体验差
- 加密 skill 脚本：工程复杂度高，影响执行性能

### 决策 2：工具层拦截实现位置

**选择**：在 `read_file_tool` 和 `bash_tool` 的入口函数中增加路径检测，而非在沙箱提供者层

**理由**：
- 工具层有完整的虚拟路径上下文（`/mnt/skills/`），容易检测
- 沙箱提供者层看到的是宿主机物理路径，需要反向映射
- 工具层可以返回用户友好的错误消息

**替代方案**：
- 在 `LocalSandboxProvider` 层拦截：需要维护虚拟路径映射，复杂度高
- 在 `validate_local_tool_path()` 中增加规则：该函数只验证路径合法性，不适合做内容保护

### 决策 3：Skill 源码检测模式

**选择**：基于路径模式匹配 + 文件扩展名

**检测规则**：
- `/mnt/skills/**/*.py` — 拒绝读取
- `/mnt/skills/**/*.md` 且路径包含 `SKILL.md` — 拒绝读取（允许读取 skill 目录下的其他文档如 README）
- `/mnt/skills/**/*.yaml` / `*.json` — 允许读取（配置和元数据，非核心逻辑）

**理由**：
- .py 文件包含核心业务逻辑，必须保护
- SKILL.md 包含完整的脚本调用指令和架构细节，必须保护
- 配置文件（yaml/json）通常不含敏感逻辑，允许读取便于调试

**替代方案**：
- 保护所有文件：过度限制，影响 skill 的可调试性
- 仅保护 .py：遗漏 SKILL.md 中的指令泄露

### 决策 4：Prompt 注入安全指令的位置

**选择**：在 `apply_prompt_template()` 中统一注入安全指令，而非修改每个 SOUL.md

**理由**：
- 集中管理，避免遗漏任何 Agent
- 所有 Agent（包括用户自定义 Agent）自动继承保护
- 减少 SOUL.md 的维护负担

**替代方案**：
- 在每个 Agent 的 SOUL.md 中手动添加：容易遗漏，用户自定义 Agent 无保护
- 通过 MemoryMiddleware 注入：Memory 用于用户偏好，不适合系统级安全指令

### 决策 5：Phase 2 Prompt 注入优化（延后）

**选择**：Phase 1 不修改 SKILL.md 的完整注入机制，Phase 2 评估

**理由**：
- Phase 1 的工具层拦截已足够防止源码泄露
- 修改 prompt 注入机制可能影响 Agent 对 skill 用法的理解
- 需要先在 Phase 1 验证多层防护的有效性，再决定是否优化

**替代方案**：
- Phase 1 就实施：风险过高，可能破坏现有 skill 功能
- 永不实施：如果 prompt 注入优化能减少 token 消耗，值得在 Phase 2 评估

## Risks / Trade-offs

**[风险] 工具层拦截可能误判**：
- 如果 Agent 试图读取 `/mnt/skills/custom/daily-report/README.md`（允许的），但路径模式匹配错误地将其视为 SKILL.md → 拒绝
- **缓解**：精确匹配路径模式，测试覆盖各种边界情况；返回清晰的错误消息便于调试

**[风险] Prompt 指令可能增加 token 消耗**：
- 在系统提示中注入安全指令会增加每次对话的 token 消耗
- **缓解**：安全指令控制在 100 字以内；Phase 2 评估是否可以通过 Memory 机制按需加载

**[风险] 用户可能通过间接方式获取源码**：
- 例如让 Agent 执行 `python -c "import ast; print(ast.dump(ast.parse(open('/mnt/skills/...').read())))"` 解析 AST
- **缓解**：bash 审计中间件增加对 `open()` 和 `__import__` 的检测；但完全防止间接泄露难度大，接受残余风险

**[权衡] 保护强度 vs 调试便利性**：
- 完全禁止读取 skill 目录会让 skill 开发者难以调试
- **选择**：允许读取 skill 目录结构（ls）和非敏感文件（README、yaml），仅保护 .py 和 SKILL.md

**[权衡] Phase 2 prompt 注入优化的收益 vs 风险**：
- 减少 skill 内容注入可以降低 token 消耗和 prompt injection 风险
- 但可能导致 Agent 对 skill 用法理解不足，影响功能正确性
- **选择**：Phase 2 先在小范围 Agent 上试验，验证功能无损后再全量推广
