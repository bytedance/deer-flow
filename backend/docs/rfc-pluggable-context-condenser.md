# [RFC] 为 DeerFlow 引入可插拔的上下文压缩器(Context Condenser)管线

## Summary

我认为 DeerFlow 的上下文管理这块**底子已经很扎实**了——`SummarizationMiddleware`(继承 LangChain)做 LLM 摘要、`ToolOutputBudgetMiddleware` 把超预算的工具输出卸载到磁盘并留文件引用(#3416)、技能文件跨摘要保留、`before_summarization` 钩子、token 计数可配。这套在"单一长会话"场景下够用。

但它有一个结构性限制:**压缩策略是单体的、写死在一条 LLM-摘要路径里**。对一个定位"长程 SuperAgent"的系统,真正的瓶颈往往不是"会不会摘要",而是"**能不能按内容类型用不同代价压缩、并把这些策略组合起来**"。

OpenHands 在 2025 年把这块抽象成了一个**可插拔的 Condenser 接口 + 管线**(`CondenserBase` / `RollingCondenser` / `LLMSummarizingCondenser` / `BrowserOutputCondenser`),不同压缩器服务不同目的、可组合成 pipeline。我认为这个模式值得借鉴到 DeerFlow——不是推翻现有实现,而是把现有的摘要逻辑**收敛成"其中一个 condenser"**,再让它可扩展、可组合、可配置。

> 参考:[OpenHands Context Condensation](https://www.openhands.dev/blog/openhands-context-condensensation-for-more-efficient-ai-agents) · [Condenser docs](https://docs.openhands.dev/sdk/guides/context-condenser)

## Problem

当前压缩只有一条路:`DeerFlowSummarizationMiddleware._maybe_summarize` → 到阈值 → 把 cutoff 之前的消息整体丢给 LLM 摘要 → 用一段 summary 替换。这带来几个具体问题:

1. **所有内容一视同仁地走"LLM 摘要"**。但很多上下文根本不需要(也不该)花一次 LLM 调用去压:
   - 一次 `web_fetch` / `jina` / browser 抓回的几千 token 网页正文,过了几轮就只需要保留"抓了什么、结论是什么",可以**无 LLM、纯规则**地裁掉。OpenHands 专门为此做了 `BrowserOutputCondenser`。
   - 早期的大段工具观察,`head+tail` 截断往往比 LLM 摘要更便宜也更安全。
2. **策略不可组合**。想"先廉价裁掉旧的网页/工具正文,只对真正的对话历史做 LLM 摘要"——现在做不到,只能要么全摘、要么不摘。
3. **策略不可扩展 / 不可 A/B**。社区想试"按 todo 状态保留""按工具类型 mask"等策略时,没有一个干净的插入点,只能改 `SummarizationMiddleware` 本体。
4. **摘要 prompt 是通用的**。`summarization.summary_prompt` 默认 `None` → 回退 LangChain 通用摘要 prompt。但 DeerFlow 是长程 agent,OpenHands 的经验是:**摘要应聚焦"用户目标 / 已完成进度 / 待办 / 关键决策"**,这样续跑时模型不丢线索。现在的默认没有针对这个场景。

结论:DeerFlow 缺的不是"再加一种摘要",而是一个**可插拔、可组合的上下文压缩层**。

## Goals

- 定义一个最小的 `Condenser` 协议:`condense(messages) -> messages`(同步/异步双形态,和现有中间件一致)。
- 把现有的 LLM 摘要逻辑收敛为一个 `LLMSummarizingCondenser`,**行为默认完全不变**(向后兼容现有 `summarization.*` 配置)。
- 支持把多个 condenser 组成 **pipeline**,按顺序运行(便宜的先跑、LLM 的后跑)。
- 提供至少一个**无 LLM 的廉价 condenser**做示范:`ToolOutputAgeCondenser`(或 `WebOutputCondenser`)——把超过 N 轮的指定工具(`web_fetch`/`web_search`/browser 类)观察正文裁成"调用摘要 + 文件引用",复用已有的 `ToolOutputBudgetMiddleware` 卸载机制。
- 为 LLM 摘要器提供一个 **DeerFlow 长程定制默认 prompt**(目标/进度/待办/决策结构化),仍可被 `summarization.summary_prompt` 覆盖。
- 配置化:`summarization.condensers: [...]`(留空 = 现有单体摘要行为)。

## Non-Goals

- 不动记忆系统(那是 `agents/memory/*` + Memory 路线图 #2450 的范畴,另有 RFC)。
- 不改中间件链顺序,也不替换 `ToolOutputBudgetMiddleware`——它是 condenser 的**互补层**(per-result 预算 vs 跨历史压缩),condenser 复用它的卸载工具。
- 不在第一版引入跨进程/分布式压缩缓存。
- 不改 LangGraph 的 checkpoint 语义。

## Proposal(草案)

```python
class Condenser(Protocol):
    def should_condense(self, messages, total_tokens) -> bool: ...
    def condense(self, messages) -> list[AnyMessage]: ...       # 同步
    async def acondense(self, messages) -> list[AnyMessage]: ...  # 异步
```

- `LLMSummarizingCondenser`:封装现有 `_maybe_summarize` 的 cutoff/partition/skill-rescue/summary 逻辑,**逐字搬迁**,默认即现状。
- `ToolOutputAgeCondenser`(无 LLM):扫描 `messages`,对 `tool_name in {web_fetch, web_search, ...}` 且年龄 > `keep_recent_n` 的 `ToolMessage`,用 `ToolOutputBudgetMiddleware` 的 `_externalize_*` 把正文换成"文件引用 + 一行预览"。纯规则、零模型调用。
- `CondenserPipeline`:`DeerFlowSummarizationMiddleware.before_model` 改为依次跑配置的 condensers;空配置 = 只有 `LLMSummarizingCondenser` = **现状**。
- 入口不变:仍是那一个 summarization 中间件,只是内部把"怎么压"委托给可配置的 condenser 列表。

这样做的好处:**改动是加法、默认零行为变化、可被维护者按需启用**,符合 DeerFlow 一贯"先不破坏现状"的风格。

## Alternatives considered

- **继续往 `SummarizationMiddleware` 里堆 if/else**:每加一种策略就改本体,耦合高、不可组合、难测试。否决。
- **只改默认 summary prompt**:能解决 Problem #4,但解决不了 #1–#3(组合/扩展);而且单独翻默认 prompt 是主观改动、缺 eval 支撑,价值有限。建议把它并入本 RFC 作为"LLM condenser 的默认 prompt"一起讨论。
- **完全照搬 OpenHands 的 event-stream + RollingCondenser**:架构差异大(DeerFlow 是 LangGraph message-list,不是 action/observation event stream),直接移植成本高。本 RFC 只借**接口与组合思想**,落到 DeerFlow 自己的 message-list 模型上。

## Open Questions

1. Condenser 该住在 `SummarizationMiddleware` 内部(委托),还是提升为独立的中间件序列?倾向前者(改动小、入口稳)。
2. `summarization.condensers` 的配置形态:类路径列表(`use:` 风格,和 `tools[]` 一致)还是枚举名?倾向前者,复用 `reflection.resolve_*`。
3. 默认长程 prompt 的具体措辞 + 是否需要一份最小 eval(几条长会话回放对比)来支撑默认值变更。
4. 异步形态:`acondense` 里的 LLM 调用与无 LLM condenser 如何在 pipeline 里混跑(无 LLM 的可同步、LLM 的需 await)。

## 如果方向认可

我可以按"默认零行为变化"的原则分两步落地:① 把现有摘要抽成 `LLMSummarizingCondenser` + `CondenserPipeline` 骨架(纯重构 + 回归测试,行为不变);② 加第一个无 LLM 的 `ToolOutputAgeCondenser` + 长程默认 prompt(带回归测试)。每步独立、可单独 review。

---

*提出者:[@ly-wang19](https://github.com/ly-wang19)。先开 RFC 对齐方向,认可后再提实现 PR。*
