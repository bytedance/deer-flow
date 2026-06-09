## 1. Prompt-level Protection

- [x] 1.1 在 `backend/packages/harness/deerflow/agents/lead_agent/prompt.py` 的 `apply_prompt_template()` 函数中添加安全指令注入逻辑，生成包含 skill 源码保护禁令的文本段
- [x] 1.2 验证安全指令被正确注入到所有 Agent 的系统提示中（builtin、tenant、user）
- [x] 1.3 编写测试验证 prompt 注入不破坏现有系统提示结构

## 2. Tool-level read_file Protection

- [x] 2.1 在 `backend/packages/harness/deerflow/sandbox/tools.py` 的 `read_file_tool` 函数中增加路径检测逻辑，识别 `/mnt/skills/**/*.py` 和 `/mnt/skills/**/SKILL.md`
- [x] 2.2 实现错误消息返回："Error: Access to skill source code is not permitted"
- [x] 2.3 验证非敏感文件（README.md、.yaml、.json）可正常读取
- [x] 2.4 编写单元测试覆盖：.py 拦截、SKILL.md 拦截、README.md 放行、.yaml 放行

## 3. Tool-level bash Protection

- [x] 3.1 在 `backend/packages/harness/deerflow/sandbox/tools.py` 的 `bash_tool` 函数中增加命令检测逻辑，识别 `cat`/`head`/`tail`/`less`/`more`/`vim`/`nano` + `/mnt/skills/` + `.py`/`SKILL.md` 模式
- [x] 3.2 增加 Python `open()` 读取 `/mnt/skills/` 的检测模式
- [x] 3.3 验证正常 skill 执行（`python /mnt/skills/...`）不被拦截
- [x] 3.4 编写单元测试覆盖：cat 拦截、head 拦截、python open() 拦截、正常执行放行

## 4. Sandbox Audit Middleware Enhancement

- [x] 4.1 在 `backend/packages/harness/deerflow/agents/middlewares/sandbox_audit_middleware.py` 的 `_HIGH_RISK_PATTERNS` 或 `_MEDIUM_RISK_PATTERNS` 中添加 skill 源码读取规则
- [x] 4.2 验证 skill 源码读取命令被分类为 `block`
- [x] 4.3 验证正常 skill 执行命令被分类为 `pass`
- [x] 4.4 编写单元测试覆盖：audit 拦截、audit 放行

## 5. Integration Testing

- [x] 5.1 编写端到端测试：用户请求查看 skill 源码 → Agent 拒绝 → 用户看到安全提示
- [x] 5.2 验证现有日报生成流程不受影响（ai-report--daily Agent 正常调用 skill）
- [x] 5.3 验证现有故障诊断流程不受影响
- [x] 5.4 运行完整测试套件 `make test`，确保无回归

## 6. Documentation

- [x] 6.1 更新 `backend/CLAUDE.md` 添加 skill 源码保护机制说明
- [x] 6.2 更新 `docs/ARCHITECTURE.md` 添加安全保护层次描述
- [x] 6.3 在 `openspec/changes/skill-source-protection/` 添加实施总结（可选）
