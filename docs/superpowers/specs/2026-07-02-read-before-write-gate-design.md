# 产物层：修改已存在文件前强制先读（ReadBeforeWriteMiddleware）— 设计

对应 issue #3857（parent）产物层子项。目标：用确定性的"版本闸"逼 agent 在修改已存在文件前看见文件现状，治"只追加、不回读"导致的重复产出（Case 2），并作为通用的文件写入新鲜度护栏。

定位（采纳 issue 评论区共识）：本机制是**新鲜度护栏**——保证"agent 读过当前版本"，不保证"最终产物无语义重复"。后者（结构化产物状态、终稿去重校验）是独立后续项。

## 行为规格

**闸规则**（与 issue 描述一致）：

1. `read_file` 成功 → 系统记录该路径的 read-mark：`sha256(当前完整文件内容)`。带行号范围/被截断的读同样记 mark（hash 始终基于完整文件内容）。
2. `write_file(append=True)`、`write_file` 覆盖**已存在**文件、`str_replace` 执行前：校验"该路径最新 read-mark 的 hash == 当前文件 hash"。不通过 → 拦截，不执行写入，返回引导性错误（"请先读该文件"；对 append 场景提示读尾部若干行即可，控制上下文成本）。
3. 写入**永不**刷新 mark：任何成功写入都会改变文件 hash → 上一次读立即过期 → 连续修改之间被逼重读。这是治 Case 2 的关键强制点。
4. `write_file` 写不存在的文件（新建）→ 放行，不记 mark（新建后的第一次 append/str_replace 也要求先读）。
5. `str_replace` 目标文件不存在 → 放行，由工具自身返回 not-found 错误。

**read-mark 与上下文存活的绑定**（issue 第三小项）：

- mark 不落 ThreadState，而是附着在 `read_file` 返回的 `ToolMessage.additional_kwargs["deerflow_read_mark"]` 上（`{path, hash}`）。
- 闸校验时从 `state["messages"]` 由新到旧扫描该路径的 mark。总结（summarization）删掉该 ToolMessage ⇒ mark 自然消失 ⇒ 闸拦截。"闸通过但内容已被总结删掉"被结构性排除，无需保留区，也无需 summarization hook。
- 推论：同一轮并行 read+write 同一文件会被拦——此时模型尚未看到读结果，拦截语义正确。

**失败语义**：

- 闸自身读文件/求 hash 出现意外错误（非 FileNotFoundError，如二进制 UnicodeDecodeError、沙箱瞬时故障）→ fail-open 放行并记日志。护栏不应把 agent 砖死。
- 非本地沙箱（AIO/E2B）的 `read_file` 把读失败（含文件不存在）吞成 `"Error: ..."` 字符串而不抛异常：闸读到以 `Error:` 开头的内容按"无法检视"处理 → fail-open 放行、不打标记。新建文件因此在这类沙箱上正常放行；已存在文件的正常读写不受影响（#3912 review 修复）。
- 拦截返回 `ToolMessage(status="error")`，措辞引导恢复路径，不暴露后端配置细节。

**并发语义（#3912 review 修复）**：

- LangGraph 会并发执行同一条 AIMessage 里的多个 tool_calls。中间件对每个 (thread, 规范化路径) 持有独立锁，把"闸校验 + 写入执行"以及"读取执行 + 打标"分别放进同一临界区：同轮第二个同路径写必须等第一个完成后再校验（hash 已变 → 确定性拦截）；读的标记保证 hash 的是模型实际看到的那个版本。该锁与工具内部的 `file_operation_lock` 分属不同命名空间，无嵌套获取，不会死锁。

## 实现结构

- 新文件 `packages/harness/deerflow/agents/middlewares/read_before_write_middleware.py`：`ReadBeforeWriteMiddleware(AgentMiddleware)`，实现 `wrap_tool_call` / `awrap_tool_call`。
  - 读状态由中间件逻辑持有/解释，工具零改动、不持状态（issue 要求）。
  - 当前文件内容读取复用 `deerflow.sandbox.tools` 的路径解析与沙箱读取逻辑（提取一个共享 helper，避免复制 `_resolve_*` 细节）；对 local 与 AIO 沙箱一致生效。
  - mark 的路径键：对 agent 提供的虚拟路径做 `posixpath.normpath` 规范化。
- 装配位置：`tool_error_handling_middleware.py::_build_runtime_middlewares` 的 `tail` 层、`SandboxAuditMiddleware` 之后 / `ToolErrorHandlingMiddleware` 之前 → lead 与 subagent 共同生效（issue：通用机制）。#3809 的链序 pin 测试同步更新。
- 配置：新增 `deerflow/config/read_before_write_config.py`（`enabled: bool = True`），挂到 `AppConfig.read_before_write`；`config.example.yaml` 增段并 bump `config_version`。默认开启（issue 第 4 点：护栏要真正生效）。
- 工具描述：`write_file` / `str_replace` docstring 增补"目标文件已存在时须先读到当前版本，过期写入会被拒绝"的提示，使模型可自解释错误。

## 已知边界（记录，不在本项处理）

- 语义重复仍可能发生（读了现状仍决定再追加同一节）——ShenAC-SAC 评论指出的产物状态/终稿校验属后续项。
- `bash` 修改文件不走闸；但它改变 hash，会使后续 `write_file`/`str_replace` 被逼重读，方向一致。
- ~~闸校验与实际写入之间存在极窄的 TOCTOU 窗口（并行工具调用），作为护栏可接受。~~ 该窗口已按 #3912 review 意见通过 per-path 临界区消除（见"并发语义"）——同轮并行重复写正是 Case 2 的变体，不应写掉。

## 测试（TDD，`backend/tests/test_read_before_write_middleware.py`）

覆盖：新建放行；未读改已存在文件（overwrite/append/str_replace）拦截；读后放行；写后 mark 过期、再写拦截、重读后放行；mark 随消息被删（模拟总结）后拦截；范围读也记 mark；hash 失败 fail-open；str_replace 不存在文件放行；`enabled=False` 全透传；同步与异步路径；链序 pin 测试更新。
