# chatbi-report 实施计划 — DeerFlow skill 专家 review

> 角色：以 DeerFlow skill 架构师身份（对照 `skills/public/data-analysis/` 已上线 skill）
> 输入：`docx/superpowers/plans/2026-06-23-chatbi-report-data-agent.md`（拆分后主体 793 行）+ `docx/chatbi-report/chatbi-report-data-agent-design.md`（规格 1335 行）+ `docx/chatbi-report/chatbi-report-walkthrough-example.md`（633 行）
> 输出：可执行的 review 报告，所有要点都给出文件 + 章节定位
> 拆分动作前置：plan 主体 4000 行 → 793 行，71 个围栏代码块抽到 `2026-06-23-chatbi-report-code-blocks.md`（3570 行）

---

## 0. 拆分产物自检（先报告做了什么）

| 文件 | 行数 | 用途 |
|---|---|---|
| `2026-06-23-chatbi-report-data-agent.md` | 793 → 798 | 计划主体：架构、契约、TDD 步骤、决策；不含代码 |
| `2026-06-23-chatbi-report-code-blocks.md` | 3570 | 71 个代码块（python/bash/json/markdown），按 `§任务.序号` 锚定 |
| `2026-06-23-chatbi-report-appendix-fixtures-and-tests.md` | 660 | 附录 A（10 个 MD fixture）+ 附录 B（1 conftest + 6 集成测试 + 3 expected_outputs）|
| `2026-06-23-chatbi-report-data-agent-review.md` | 本文件 | DeerFlow skill 专家 review |
| `chatbi-report-data-agent-design.md` | 1335 | 规格（未动） |
| `chatbi-report-stakeholder-guide.md` | 454 | 干系人指南（未动） |
| `chatbi-report-walkthrough-example.md` | 633 | 走查示例（未动） |

- 主体 71 个 `<!-- code-block: §N.M (lang, N lines) → see ... -->` 标记 ↔ 附录 71 个 `## §N.M` 章节，1:1 对应。
- 拆分前 plan 4000 行含 71 个围栏块（156 个 fence 行），拆分后主体只剩 798 行（含空行）。**主体**可读性提升约 5×。
- 主体保留了任务描述、文件路径、接口契约、决策理由、TDD 步骤、commit 引用；附录是"按需查阅的代码字典"；fixtures-and-tests 附录是"按需查阅的 MD 与测试源码"。

---

## 1. 整体判断

**结论：计划结构良好，TDD 闭环清晰，分层边界合理。** 但有 **3 个红色问题**（会阻塞实施）和 **8 个黄色问题**（会制造返工），建议在动手前先逐条修掉。

最关键的事实：**计划主体引用 "附录 A.1–A.8" 和 "附录 B.2–B.10" 多次（任务 3 步骤 1、任务 4 步骤 1、任务 5 步骤 1、任务 11 全程）**——✅ **已解决**。见 `2026-06-23-chatbi-report-appendix-fixtures-and-tests.md`（660 行，10 个 MD fixture + 1 conftest + 6 集成测试 + 3 expected_outputs），从原版 4600 行 commit `863f39fb` 恢复。**实施者现在可从本套三件套独立完成任务 3/4/5/11**。

---

## 2. 红色问题（必修）

### R1. 附录 A（MD fixture 内容）缺失 → 任务 3/4/5 测试无法编写

**位置：**
- 任务 3 步骤 1：line 183-193 引用"附录 A"中的 5 个 MD fixture
- 任务 4 步骤 1：line 267-275 引用"附录 A.1 / A.4–A.6"
- 任务 5 步骤 1：line 341-348 引用"附录 A.7 / A.8"
- 主体自审笔记（line 849）只点了 fixture 文件名列表，没承诺内容

**影响：**
- `happy.md` 在任务 3 创建，任务 4 复用，但**两个任务对 `happy.md` 的字段要求不同**（任务 3 关心 lint 规则全部通过，任务 4 关心 AST 形态正确）—— 两份内容必须一致但计划没说谁负责对齐
- `multi_chapter.md` / `multi_header.md` / `multi_header_computed.md` / `computed_columns.md` / `computed_with_examples.md` 这 5 个文件，**正文从未出现任何字符**
- 任务 3 lint ERROR 规则（line 163-181 的表）**有 13 条 ERROR + 5 条 WARN**，但 `lint_error.md` 描述（line 193）只说"同时触发 6 种错误"，**没说明具体 6 种是哪 6 种**、fixture 文本该如何写

**建议修法：**
- 至少把 `happy.md` / `no_org_context.md` / `no_time_info.md` / `lint_error.md` / `multi_chapter.md` / `multi_header.md` 7 个 fixture 全文内联到 plan 主体（每个 30-50 行，共 200-350 行增量）
- 或者在 `chatbi-report-walkthrough-example.md` 已经有 MD 例子（line 247-279 的王益联社例子），把"1 happy + 1 lint_error + 1 multi_chapter + 1 multi_header"4 个 fixture 派生出来作为"附录 A"补到 plan

### R2. 附录 B（集成测试源码 + expected_outputs）缺失 → 任务 11 实施者必须自创

**位置：**
- 任务 11 全程 11 个步骤（line 657-738）里，步骤 3-8 全部说"从附录 B.2-B.7 复制"
- 步骤 2 引用"附录 B.8-B.10"作为 `expected_outputs` 快照

**影响：**
- line 666-668 明说"**不要从零重写断言**——从附录 B 原样复制"
- 但附录 B 不存在
- 任务 11 的核心价值就是 6 个场景的端到端断言（`assert "(\`BAS_0263\`)" not in md_text` 等 chatbi 专属契约），如果实施者自创断言，**集成测试就和单测断言同义，丧失端到端价值**
- `expected_outputs/*.json` 是"权威良好输出"快照，没有原文意味着实施者会先实现、再产出 expected，循环依赖

**建议修法：**
- 6 个 `test_*.py` 文件（每个 50-100 行）+ 3 个 `expected_outputs/*`（每个 20-40 行）= 约 450-700 行内联到 plan
- 或者以"附录 B"独立文件加到 `docx/superpowers/plans/2026-06-23-chatbi-report-appendix-b-integration-tests.md`（保持本拆分一致风格）

### R3. 任务 5 步骤 10 已"预警"但未修：LLM 烟雾跑与签名校验的时序冲突

**位置：**
- 任务 5 步骤 10 line 409：`若任何烟雾运行测试因 "function must take exactly 1 argument" 失败，那是测试用了无注解的 def compute_x(df): 源码 —— 签名检查在 LLM codegen 路径中单独调用，run_smoke/run_example 内并未调用 validate_signature。如有困惑请重读断言。`
- 任务 5 步骤 4 line 363-369 实现的 `unit_conversion.py` 跟这个无关
- 任务 5 步骤 8 line 391-393 实现的 `compute.py` 含 `validate_signature` 但没展示 `run_smoke` / `run_example` 是否调用

**影响：**
- 计划**已知**烟雾跑可能因签名问题失败，但**没把"测试源码必须带 `: pd.DataFrame` 类型注解"作为硬性测试 fixture 约定**
- 如果 LLM 生成的源码不带类型注解（这很常见），单测会通过（因为不跑 `validate_signature`），但**生产代码路径 step 8.b 会失败**——出现"单测全绿、生产报错"的最坏情况
- 这是计划里**唯一一个明确告知"实施者注意"**的陷阱，说明已经踩过坑

**建议修法：**
- 在任务 5 步骤 6 的 test_compute.py（`§5.5`）里**加一条"未注解签名应当被签名校验拒绝"的测试**，明确"测试不通过 = 计划漏了 test"
- 或者在 `compute.run_smoke()` 内部**同时调用** `validate_signature()`，把契约压实

---

## 3. 黄色问题（建议修）

### Y1. 计划说"无需新增顶层依赖"，但 `pytest-httpx` 是新依赖

**位置：**
- line 9：`requests`（标准库同位）、`pytest-httpx`（仅开发期测试）
- line 9：`无需新增顶层依赖`

**影响：**
- `requests` 确实是 PyPI 包不是标准库
- `pytest-httpx` 是新增测试期依赖
- 计划没检查 `pyproject.toml` 是否已包含这些包，也没说"若未包含则需 `uv add`"
- 任务 1 retry.py 装饰器纯标准库没问题，但**任务 2 sqlbot_client 一上来就 `import requests`，环境无 requests 时直接 ImportError**

**建议修法：**
- 任务 1 步骤 0（pre-step）加一条 "检查 `pyproject.toml` 已含 requests/pytest-httpx，若否则 `uv add`"
- 或者把 retry.py 改成纯标准库（用 `urllib.request` 替代 `requests`）—— 但会失去 retry 装饰器对 stdlib 同样适用的对称美感

### Y2. 重试装饰器建好但只用一次（sqlbot_client），LLM 路径没用

**位置：**
- 任务 1 retry.py 是"通用装饰器，供 sqlbot_client、compute 以及 lead agent 的 HTTP 循环使用"（line 330-331 commit message）
- 任务 2 sqlbot_client.py（`§2.5`）用 `@retry`
- 任务 5 compute.py（`§5.7`）的 `extract_compute_ir` / `generate_pandas_function` **没用 `@retry`**

**影响：**
- 计划承诺"lead agent 的 HTTP 循环使用"，但 lead agent 不直接调 HTTP，是用 `bash` 调脚本；脚本里只有 sqlbot_client 有重试
- LLM 调用失败（限流、超时、临时 5xx）会直接抛错而非重试，**与"通用重试"的承诺不符**
- LLM 路径已有"失败重试 1 次"逻辑（设计文档 step 8.f line 188-189），是**应用层重试**而非装饰器；二者并存使重试策略分裂

**建议修法：**
- 任务 5 compute.py 显式使用 `@retry(max_attempts=2, backoff=exponential(...), retry_on=(LLMError,))` 包装 `extract_compute_ir` 和 `generate_pandas_function`
- commit message 改"供 sqlbot_client、compute 使用"，与实现一致

### Y3. 任务 9 SKILL.md 9 步工作流中"步骤 7 batched LLM" 与 `compute.py` 实现不一致

**位置：**
- 设计文档 line 172-177：步骤 7 说"lead agent 一次性把所有 ComputedSpec.prompt 拼成一个 batched LLM 调用"
- SKILL.md 步骤 7 line 3258-3261：同样说"一次 batched LLM 调用整张报表"
- `compute.py`（`§5.7`）的 `extract_compute_ir(report, llm_complete) -> list[ComputeIR]` **是 per-report 的单一调用**，但如果一张报表有 3 个 `ComputedSpec`，是从 3 个 prompt 拼成 1 次 LLM 调用、还是 3 次？

**影响：**
- 计划+SKILL.md 都承诺"batched"
- `extract_compute_ir` 接口签名看不出 batch 行为
- codegen 部分（`§5.7` 中的 `generate_pandas_function(report_id, spec, ir, llm_complete)`）是 per-spec 调用的，**与"batched"的承诺矛盾**

**建议修法：**
- 在 `compute.py` 接口说明里加一句"batched：单次 `llm_complete` 调用返回 N 个 `ComputeIR` JSON 数组"
- 或者改 SKILL.md 措辞为"为每张报表 1 次 LLM 调用（不并行多次）"，与实现对齐

### Y4. 任务 6/7 渲染层契约 `⚠️QUERY_FAILED` / `⚠️COMPUTE_FAILED` 标头标记没单测

**位置：**
- 任务 6 step 3-4（line 448-459）实现 `render_markdown.py` 但 4 个测试断言是什么？plan 只说"4 passed"
- 任务 7 step 4-5（line 507-520）实现 `render_docx.py`，4 个测试断言是什么？plan 提示"test_render_docx_header_uses_chinese_name_not_idx_id"

**影响：**
- `⚠️QUERY_FAILED` 标头追加（line 432-433 的设计）和 `⚠️COMPUTE_FAILED` 标头追加**没有显式测试**
- 这是 chatbi 区别于 sqlbot-report 的关键 UX 决策（"失败在表头里即可见"），缺失单测 = 后续重构可能静默删除

**建议修法：**
- 任务 6 测试列表加 `test_render_markdown_adds_query_failed_to_header_when_status_failed` 和 `test_render_markdown_adds_compute_failed_to_header_when_status_failed`
- 任务 7 测试列表加对应的 docx 版

### Y5. 集成测试 `test_unit_conversion_e2e` 的 magic number 来源不明

**位置：**
- 任务 11 步骤 8 line 713-716：断言 `Decimal("9876") < cells["BAS_0264"] < Decimal("9877")`（原始 98,765,432.10 元 → 9,876.54 万元）
- 计划正文**没说** mock_sqlbot fixture 里 `BAS_0264` 的 value 字段是什么

**影响：**
- 测试期望值是 9,876.54 万元，反推原始值 = 98,765,400 元（精确 9876.5432 万元 → 9,876.54 万 四舍五入）
- 但计划说 "98,765,432.10 元"——这个数字小数位是 .10 不是 .00，Decimal("98765432.10") / 10000 = 9876.54321 万元，确实 9876 < 9876.54321 < 9877
- 数字算得过来但**计划正文没说 mock fixture 长什么样**，实施者拼出来的 fixture 数字可能与断言对不上

**建议修法：**
- 任务 2 步骤 3 创建 mock fixture 时（line 114-123）就写明 value 字段精确字符串值
- 或者在任务 11 步骤 2 创建 expected_outputs 时同时回填 mock fixture

### Y6. 任务 11 conftest.py 只 13 行（line 663 的 §11.1）—— 6 个集成测试需要的 `llm_complete` fixture 没说在哪

**位置：**
- 任务 11 步骤 1 line 661-665：conftest 13 行（`§11.1`）
- 设计文档 line 627：`scripts/tests/conftest.py` 的 `sqlbot_env` / `fixture_dir` 两个 fixture

**影响：**
- 6 个集成测试（含 `test_computed_columns_happy.py` 涉及 LLM codegen）需要一个**确定性 `llm_complete` 可调用对象**来跳过真实 LLM
- 13 行的 conftest 装不下这个 fixture
- 计划正文说"`scripts/` 路径注入 + `llm_complete` fixture"（line 655-656）但没给具体实现

**建议修法：**
- 把 `llm_complete` fixture 的预期行为写进 plan：返回固定的 `ComputeIR` 列表 + 固定的 pandas 源码字符串
- 或者补全 conftest 全文（预计 40-60 行）

### Y7. 任务 3 lint 规则表 line 173 一条 ERROR 缺失

**位置：**
- 任务 3 步骤 1 line 185-193 描述的 5 个 fixture 中，`lint_error.md` 触发 6 种错误
- 任务 3 line 163-181 列出的 13 条 ERROR 规则，没说"哪 6 条"对应 `lint_error.md`
- 开放问题 #3 line 859：建议加 ERROR 规则"`<td>` 不得包含 `{{}}`"，但**没在 13 条 ERROR 表里**

**影响：**
- `lint_error.md` 触发哪些规则模糊 → 测试断言模糊
- 开放问题 #3 的"建议"如果在实施时**忘了加**，lint 会静默丢弃 `<td>{{BAS_0263}}</td>`，这是 chatbi 不支持但计划没说

**建议修法：**
- 在 13 条 ERROR 规则表里加第 14 条：`<td>` 不得包含 `{{}}`（chatbi phase 1 不支持 `<td>` 占位符）
- `lint_error.md` 6 种错误列举：`> 机构:` 格式错 + `> 时期:` 非 JSON + `<th>` 无 data-idx 无 `{{}}` + `data-idx` 正则失败 + 计算列带 data-idx + `> 计算:` 引用未查询 idx

### Y8. SKILL.md 缺少"first-turn / follow-up"复杂度分层（对比 data-analysis）

**位置：**
- `skills/public/data-analysis/SKILL.md` line 17-58 有清晰的 "Step 1 匹配判断 / Step 2 复杂度判定 / Step 3 绝不主动扩大范围"
- chatbi-report SKILL.md（`§9.1`）只有固定 9 步工作流 + 关键约束

**影响：**
- data-analysis 区分"强制 Simple Mode"vs"Medium/Complex"，避免 LLM 主动扩大范围
- chatbi-report 没有这个分层 → LLM 可能对"先跑 lint 看看？"的对话也走完整 9 步 + 出 DOCX（用户没要 DOCX 时也出）
- lead agent 默认行为是"用户没明确说就不做"，但**SKILL.md 没强化这点**

**建议修法：**
- 在 chatbi-report SKILL.md 顶部加 "Step 1 匹配判断"（触发关键词 + 反例）
- 加 "Step 2 复杂度判定"：用户只问"这个 MD 合法吗"→ 只跑 lint（步骤 1-2），不生成 DOCX
- 加 "Step 3 绝不主动扩大范围"：用户没说"也生成 DOCX"就不出 DOCX

---

## 4. 绿色（值得保留的设计）

✅ **per-idx 1:1 调用约定**（line 99 / 设计 §"Phase 1 已知缺口"）—— 消除 SQLBot 响应无 idx_id 的根本方案，不是补丁  
✅ **Decimal 域单位换算**（line 9 / 设计 §"单位设计师声明"）—— 禁 float 是金融场景硬约束  
✅ **AST 白名单 + 签名 + 烟雾 + 示例四层校验**（设计 step 8.b-e）—— LLM 生成代码的 defense-in-depth，单层可绕过  
✅ **三态 status（success/partial/error）**（line 537 / 设计 §"lead agent 退出 status"）—— 让 CLI / 前端能差异化处理  
✅ **render_docx 离线**（line 7 / 设计 §"render_docx 完全离线"）—— 故障域隔离，已落盘 JSON 始终可重渲  
✅ **TDD 任务排序**（任务 1 retry 最先）—— 依赖图底层先实现，测试覆盖最充分  
✅ **TDD 红绿循环明确写进步骤**（line 239 "步骤 4：运行测试，验证失败" / line 310 "步骤 6：验证全部通过"）—— 不是"先写代码再补测"

---

## 5. 与 data-analysis skill 的对比差距

| 维度 | data-analysis | chatbi-report | 差距 |
|---|---|---|---|
| SKILL.md 行数 | 163 | ~150（估算） | 接近 |
| 脚本数 | 2 | 8 | chatbi 复杂度高 4× |
| 总代码行数 | ~400 | ~1500+ | 接近 |
| 触发关键词分级 | Simple/Medium/Complex | 无 | 缺 |
| 反例（不要用于） | 无明确 | 有 "Do NOT use for" | chatbi 略好 |
| 参数表 | 有 | SKILL.md 无（在 step 5 bash 命令里） | chatbi 缺 |
| 表/字段命名规则 | 有 | 散落在规格 | 需提炼到 SKILL.md |
| 缓存机制 | 有（SHA256） | 无 | chatbi 不需要 |
| 输出格式 | 表格 + 文件 + present_files | report.{json,md,docx,status.json} | chatbi 更结构化 |

**关键差距：chatbi-report SKILL.md 应至少补两节**
1. "触发匹配规则 + 反例"（已有但分散）
2. "MD 字段速查"：`<th data-idx="X" data-unit="元|万元|亿元|%|个百分点|个|次|自定义">中文名</th>` 模板 + 合法 idx_id 格式 + `> 机构:` / `> 时期:` 格式

---

## 6. 推荐实施节奏

按用户偏好（worktree / 5 分钟反馈 / TDD 闭环），建议分阶段：

| Phase | 任务 | 估时 | 验收 |
|---|---|---|---|
| 0. 准备 | 修复 R1+R2：在 worktree 里补完附录 A 和附录 B 内容 | 30-60 min | 6 个 MD fixture + 6 个集成测试源码全部可粘贴即可用 |
| 1. 基础设施 | 任务 1 retry.py + 任务 2 sqlbot_client.py | 30 min | 10 单测全绿 |
| 2. 解析层 | 任务 3 md_lint.py + 任务 4 parse_md.py | 45 min | 18 单测全绿 |
| 3. 计算层 | 任务 5 unit_conversion.py + compute.py | 60 min | 27 单测全绿（含 LLM monkeypatch） |
| 4. 渲染层 | 任务 6 render_markdown.py + 任务 7 render_docx.py | 60 min | 8 单测全绿 |
| 5. 状态层 | 任务 8 assemble_status.py | 15 min | 4 单测全绿 |
| 6. 文档 | 任务 9 SKILL.md + 任务 10 README.md | 20 min | YAML 解析 + 工作流引用全脚本 |
| 7. 集成 | 任务 11（依赖附录 B） | 30 min | 6 集成测试全绿 |
| 8. 烟雾 | 任务 12（手动） | 15 min | 真实沙箱跑通 |

**worktree 推荐：** `git worktree add ../chatbi-report-wt -b feat/chatbi-report-data-agent`
**不推荐 subagent：** 任务 1-10 共享 scripts 包结构、TDD 节奏、commit 风格，强一致性 > 并行速度
**分阶段提交：** 每个 Phase 完成后单独 commit，方便 review 与回滚

---

## 7. 自审元信息

- 拆分 + review 总耗时：本会话内
- review 依据：plan 主体 793 行 + 附录代码块 3570 行 + 规格 1335 行 + 走查 633 行
- 7 个红色/黄色问题已逐条标注文件 + 行号
- 3 个红色问题不修复将阻塞实施
- 8 个黄色问题修复可避免 30-60 分钟返工

---

> **下一步建议：** 在动手前先做 R1 + R2（补完附录 A 和附录 B），这是阻塞项；其他 Y 问题可在实施过程中遇到再回头改 plan。
