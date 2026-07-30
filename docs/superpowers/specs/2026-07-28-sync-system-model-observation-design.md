# 设计 v2：同步调用点的系统模型观察

> 补充[扩展系统 RFC](../../plans/2026-07-30-extension-system-rfc.md)。
> 起因：扩展系统 Task 12 只接线了三个异步调用点，两个同步调用点悬空。
>
> **v1 已被设计评审否决（do-not-build as written）。本文是按评审结论重写的版本。**
> v1 的错误保留在文末「v1 错在哪里」一节，因为其中两条是事实性错误，值得留档。

## 评审后的事实基线

| 事实 | 出处 | 对设计的影响 |
|---|---|---|
| `DeerFlowSummarizationMiddleware` **同时**覆盖 `before_model`（:277）与 `abefore_model`（:280） | `summarization_middleware.py` | 异步图走 `abefore_model` → `_asummarize_with`，**已经接线**。同步的 `_summarize_with` 在 Gateway 与 subagent 路径上是死代码 |
| 唯一走同步图的宿主是 `DeerFlowClient.stream()`（`client.py:930`） | 嵌入式 / TUI | 而该宿主恰恰是「不会注册 loop」的那一类 |
| `deermem/` 包**只允许一行** `from deerflow`，由测试钉死 | `tests/test_deermem_self_contained.py:262` | 在 `deermem/` 内部直接 import 宿主扩展模块会让既有测试变红 |
| `MemoryCallbacks` 已是宿主侧可观测缝隙，且其 docstring 明说「More hooks — post-extract / search / inject / error — can be added when callers need them」 | `agents/memory/manager.py:46-63` | 这就是本来就为此准备的扩展点 |
| `run_coroutine_threadsafe` 投给「已 stop 但未 close」的 loop：提交成功，future **永不 resolve** | 评审实测 | `.result(None)` 会永久阻塞 |
| `run_coroutine_threadsafe` 投给已 close 的 loop：**同步抛** `RuntimeError` | 评审实测 | 派发本身必须包 try/except |

**结论：两个同步调用点里，`_summarize_with` 一处收益为零** —— Gateway 到不了，TUI 到得了但按 v1 设计会被丢弃。
真正剩下的缺口只有一条：**DeerMem 记忆更新的 LLM 调用，且仅在 Gateway 宿主内**。

## 两个可选方案

### 方案 X：按缩减范围实现（评审的 minimum change）

1. **放弃 `_summarize_with`**，在扩展契约中写明其不可观测。
2. **DeerMem 经 `MemoryCallbacks` 接线**，不在 `deermem/` 内 import `deerflow.extensions`：
   给 `MemoryCallbacks` 增加带 no-op 默认实现的结果侧钩子（`on_memory_llm_result`），
   在 `_do_update_memory_sync_impl` 的 `model.invoke` 之后与其 `except` 分支各调一次，
   宿主侧实现放在 `LangfuseMemoryCallbacks` 旁边。可移植性契约与既有测试都不受影响。
3. **派发策略改为「只投递、不等待」**：
   ```
   若无 observer            -> 直接返回（零扩展路径不查 loop）
   若未注册 loop            -> 丢弃 + 一次性 warning
   若注册的 loop 未在运行    -> 丢弃（涵盖「已 stop 未 close」这个会挂死的状态）
   否则                     -> run_coroutine_threadsafe(注册的 loop)，保存强引用，不 .result()
   整段派发包 try/except BaseException，失败只记日志
   ```
   **永远只投给注册的那个 loop，绝不投给 `get_running_loop()`。**

   放弃阻塞等待，就同时消灭了 v1 的三个挂死/泄漏模式（F2 无界阻塞、F6 关闭竞态、F7 超时不取消），
   代价是失去「观察与调用的时序关系」—— 而评审已证明该性质的论证建立在一个不存在的线程模型上（见 F4），
   且唯一需要它的调用点是死代码。
4. **注册点**：`langgraph_runtime` 的 exit stack 首先注册 loop reset（因此 LIFO
   最后执行），随后才启动 extension service；memory drain 前只暂停新的同步
   fire-and-forget system observation，因此停机排空期间这类观察会被丢弃。注册 loop
   本身必须保留到 in-flight subagent drain 与 extension service stop 完成，供 awaited
   task/system hook 继续使用，随后才重置；同一个 exit stack 也保证任何启动失败/取消
   都会复位。提前清空会把 loop-bound lifecycle hook 错派回 subagent 隔离 loop。
5. **`set_extension_notify_loop` 必须与扩展被构造时所在的 loop 一致**，写进 docstring 并在 Task 13
   的加载点上断言。

**收益**：DeerMem 记忆更新 LLM 调用在 Gateway 内可被观察。
**成本**：一个宿主侧 loop 注册表 + `MemoryCallbacks` 新钩子 + 约 9 项新测试（含「已 stop 未 close」
的 loop、并发关闭、进程内第二个 loop 的归属断言）。

### 方案 Y：不建造，把缺口写进契约

在扩展契约中写明：`on_system_model_call` 只覆盖图外的**异步**系统模型调用；
DeerMem 的记忆更新与同步图路径的摘要调用不产生该事件。

**收益**：零运行时风险，零新增机制。
**成本**：DeerMem 记忆更新调用永久不可观察。

评审对方案 Y 的论证：契约本就容忍部分覆盖（`task_store` 可为 `None`、`detached` store、
预算耗尽时跳过 contributor），一条写明的边界与之一致；而方案 X 是在「fail-open 观测」这个目标下，
为一个条目引入三种停机期故障模式的机器。

## 我的建议

**倾向方案 X，但把它当成 DeerMem 专项而不是「同步调用点通用机制」。** 理由：记忆更新是唯一一个
真正跑 LLM、又完全在图外、且对可观测性有实际价值的路径；而经 `MemoryCallbacks` 接线不引入新的
公共扩展 API，日后若判断不值得，删除成本很低。若判断收益不抵成本，方案 Y 也是诚实的答案 —— 前提是
契约里写清楚，而不是留白。

## v1 错在哪里（留档）

1. **事实错误**：v1 称同步中间件 hook 跑在 executor 线程上、主循环 `await` 时空闲可调度。
   实际上 LangChain 用 `RunnableCallable`，只有同步实现时**直接在事件循环线程上内联执行**
   （`langgraph/_internal/_runnable.py:434-435`）。「阻塞是安全的」这一整段论证因此失效。
2. **事实错误**：v1 把 `aupdate_memory`（`asyncio.to_thread` 路径）列为 memory 的活跃调用路径。
   它**没有任何生产调用方**。
3. **自相矛盾**：v1 的分支 1 用 `loop.create_task` 投给「当前线程正在跑的那个 loop」——
   进程内有三个长生命周期 loop（Gateway、subagent 隔离循环、BoxLite 私有循环），这恰好就是
   本设计声称要避免的跨循环问题。
4. **未评估的选项**：v1 的备选表里根本没有「不建造、写进契约」这一行。
