# 设计说明：问题 → 方案 → 取舍

写给两类人：接手改这个插件的人，和面试时问「你为什么这么设计」的人。
每一节都是先说**踩到的具体问题**，再说方案，最后说**这个方案牺牲了什么**。

---

## 问题 1：Agent 有了沙箱，为什么还需要审批？

沙箱解决的是「炸不炸得到宿主机」，审批解决的是「该不该做这件事」。这是两个正交的问题。

`git push origin main` 在沙箱里执行得干干净净，不会污染任何本地文件——
但它把代码推上了远端。`rm -rf /data/prod` 在容器里也跑得很成功，
如果那个目录是 volume 挂进来的。沙箱是**隔离边界**，不是**授权边界**。

DeerFlow 两边都想到了：有 `Sandbox`（三种 provider）也有 `GuardrailProvider`。
但 guardrail 只有 allow / deny 两态——**要么放行要么拒绝，没有「等人看一眼」**。

而现实里绝大多数高风险操作既不该无脑放行，也不该一律拒绝，它们需要一个人看两秒钟。
这就是本插件补的第三态。

**取舍**：三态让链路变长了（拒绝 → 人批 → 重试），任务不再是一气呵成。
换来的是高风险操作有了人的确认点。如果你的场景里没有真正危险的操作，
不要引入这套东西，纯负担。

---

## 问题 2：为什么审批要落 SQLite 而不是弹个窗？

因为**审批的人和跑 agent 的进程通常不是同一个**，甚至不在同一台机器。

DeerFlow 的运行形态是 Gateway 服务 + 前端 + 六个 IM 渠道（飞书/钉钉/Slack…）。
一个跑在服务器上的 run 想弹窗给谁看？放内存的审批只是个弹窗，不是审批系统。

落库带来三个必需的能力：跨进程、跨时间、可追溯。
`governance approve APR-XXXX --by 张三 --note "..."` 可以在任何一台能访问这个库的机器上执行。

**取舍**：多了一个 SQLite 文件要运维，多了一个「谁来批」的流程问题。
以及热路径上多了一次 DB 查询——但这发生在工具调用前，相对工具本身的耗时可以忽略。

---

## 问题 3：为什么用「审批单」而不是 LangGraph 的 `interrupt()`？

`interrupt()` 才是"正统"做法，我最初也是奔着它去的。读源码之后改了主意。

三条证据：

1. **DeerFlow 自己没用 `interrupt()` 做中断**。它的澄清机制
   （`ClarificationMiddleware`）用的是 `Command(goto=END)`——结束本轮，
   靠用户的下一条消息续上。这说明上游的 run/thread 模型更适应「结束-重开」而不是「挂起-恢复」。

2. **子 agent 根本没法 resume**。AGENTS.md:343 原文：
   > Subagent graphs are compiled with `checkpointer=False` to avoid inheriting
   > the parent run's checkpointer, since subagents are one-shot and never resume.

   而子 agent 恰恰是最需要审批的地方——它在隔离上下文里跑，用户看不到中间过程，
   出事最难复盘。一个在子 agent 里用不了的审批机制，等于没做。

3. **Gateway 的 resume 通路我没实测**。没实测的东西不能当默认。

所以默认走「开单 + 拒绝 + 告知单号 + 重试放行」。这条路径不依赖 checkpointer、
不依赖 resume 语义、主子 agent 通吃，而且能在**完全没有 DeerFlow 的环境里被单测覆盖**。

`interrupt` 模式仍然保留在配置里（依据是 `GuardrailMiddleware` 显式
`except GraphBubbleUp: raise`，注释写着 "Preserve LangGraph control-flow signals"，
说明 provider 层就是官方给 HITL 留的口子），但标注为实验、未实测。

**取舍**：ticket 模式的用户体验不如真正的挂起——模型会先收到一次拒绝。
用「不要重试、不要绕过、可以先做别的」的明确指令把这个体验损失补回来一部分。

---

## 问题 4：审批系统最常见的失效模式是什么？

**不是被绕过，是被无脑放行。**

每次执行 `pytest -q` 都弹一次审批，人第三次就开始闭眼点「同意」，
第十次就把整个模式切成 YOLO。**审批疲劳会让审批系统在两天内退化成零。**

所以指纹机制不是优化，是必需品：

```python
compute(tool_name=..., tool_input=..., rule_id=..., scope=..., thread_id=...)
```

三档授权范围，由规则自己声明：

| scope | 含义 | 用在哪 |
|---|---|---|
| `exact` | 参数完全一致才算同一次操作 | 高危单次操作（`git push`、写 `.env`） |
| `tool` | 同工具任意参数 | 批量低危操作（子 agent 的只读 shell，批一次管 30 分钟） |
| `rule` | 命中同一条规则即可 | 大类放行 |

配合 `ttl_seconds` 做时效，配合 `thread_bound_grants` 做会话隔离
（在 A 会话批准的 `rm -rf build/` 不该自动放行 B 会话的同一条命令）。

指纹计算必须**可复现**：排序 key、剔除易变字段（`tool_call_id` / `run_id` / `sandbox_id`）、
压缩空白、截断超长值。否则一个空格就会让「批过的操作」永远命中不了，
用户会觉得「明明批过了还问」，然后又回到无脑放行。

**取舍**：`tool` 和 `rule` 范围会放大授权面。这是效率和严格性的显式交易，
所以把它做成**每条规则自己声明**，而不是全局开关——高危规则用 `exact`，低危用 `tool`。

---

## 问题 5：为什么策略要匹配参数，不能只看工具名？

`bash: pytest -q` 和 `bash: rm -rf /` 是同一个工具，风险差两个数量级。

只按工具名做策略只有两种结果：把 `bash` 全放（等于没做），或者把 `bash` 全拦
（agent 直接废掉）。两种都会让治理形同虚设。

所以规则引擎支持参数级条件（`equals` / `contains` / `regex` / `path_prefix` / `absent`），
`when` 是 AND、`when_any` 是 OR（后者专门给「危险命令黑名单」用）。

同时支持 `scope: subagent` 维度——同一条 `ls -al`，主 agent 放行、子 agent 要批。
理由同问题 3：子 agent 的中间过程用户看不见。

**求值语义刻意选了「有序 + 首条命中即返回」**，和防火墙、IAM、Nginx location 一致。
运维不需要学一套新的求值模型就能读懂 `governance.yaml`，规则冲突时的行为也是确定的。

**取舍**：正则匹配拦不住语义等价的绕过——
`python -c "import os;os.system('rm -rf /')"` 命中不了 `rm\s+-rf` 这条规则。
**这是本插件的硬边界，写在 README 里没藏着**：真正的隔离靠沙箱，
本插件是沙箱之上的授权层，不是替代品。要收紧就把 `default_effect` 改成 `ask`，
用白名单代替黑名单——代价是审批量暴增，回到问题 4。

---

## 问题 6：为什么预算要分三层五维？

DeerFlow 已经有 `TokenBudgetMiddleware`（单 run 的 token 上限），我不重复造。
补的是它没覆盖的两个失控形态：

**形态一：单 run 都不超标，但一个会话开了二十个 run。**
所以要 thread 层；再往上还有 day 层管当日总配额。三层独立计数，取最严的一条。

**形态二：失控的不是 token，是时间。**
长任务真正卡死的样子通常是「某个子 agent 在一个网页上重试了 40 分钟」——
token 消耗其实不大，但任务已经废了。所以除了 token 还要有
`tool_calls` / `delegations` / `wall_ms` / `cost_cents` 四个维度。

**两级阈值**：先 WARN（把剩余预算作为 `<system-reminder>` 注入，让模型自己收敛），
再 STOP（清空 tool_calls，让它基于已有信息收尾）。
只有硬停没有预警，任务会毫无征兆断在半路；对长任务来说，
「半成品 + 明确说明还差什么」远比一个异常堆栈有用——这一点跟 DeerFlow 自带
`TokenBudgetMiddleware` 的硬停做法保持一致，不另起一套。

**未知模型的成本记 `unknown` 而不是 0。** 把未知当零，会让整套预算体系在换模型的
那一天静默失效，而且没有任何报警——这是可观测性里最典型的伪健康状态。
`strict_pricing: true` 时直接启动报错，宁可跑不起来也不要跑了一个月才发现成本一直记成 0。

**取舍**：账本默认在内存里，进程重启清零。理由是熔断判断在热路径上，
每次读 SQLite 会把延迟带进主循环。跨进程的日配额留了 `CounterBackend` 接口，
但**没有提供 SQLite 实现**——不写没验证过的东西。

---

## 问题 7：为什么核心层要零三方依赖？

这条约束来自一个很实际的处境：**我改这个插件的机器上装不了 langgraph**
（PyPI 不可达），而 DeerFlow 完整跑起来需要 API key、Gateway、前端、沙箱。

如果把判断逻辑写进 `GuardrailProvider` 的方法体里，那我每改一次规则引擎，
唯一的验证方式就是「起整个 DeerFlow 点几下看看」。这不是验证，这是碰运气。

所以分层：

- `policy` / `fingerprint` / `budget` / `pricing` / `store` / `engine` → 只用 stdlib
- `provider` / `middleware` → 只做字段搬运和结果翻译，不含判断

结果是 45 个用例 + 端到端演示能在无网、无 key、无 DeerFlow 的环境里跑完，
而且**真的抓到了 bug**：预算判定里 `worst` 初始为 `OK`，
比较逻辑写成 `verdict_level is not STOP`，导致 WARN 永远压不过 OK、预警一次都没触发过。
这种 off-by-one 靠人肉点界面是发现不了的。

**取舍**：适配层的代码没有测试覆盖，只能靠「它很薄」来保证。
所以 INTEGRATION.md 里明确列了「锁定的上游事实」表——
上游一改字段，先看那张表。

---

## 与 DeerFlow 官方能力的边界（不重复造轮子）

| 官方已有 | 本插件的关系 |
|---|---|
| `GuardrailMiddleware` + `GuardrailProvider` | **复用**：本插件是一个 provider 实现，不新写中间件 |
| `SandboxAuditMiddleware` | **不重叠**：那是沙箱操作的安全日志，本插件是授权决策账本 |
| `TokenBudgetMiddleware` | **不重叠**：那是单 run token，本插件是三层五维 |
| `SubagentLimitMiddleware` | **不重叠**：那是并发数 ≤ 3，本插件是委派总次数与成本 |
| `LoopDetectionMiddleware` | **不重叠**：那是重复工具调用检测，本插件是预算 |
| LangSmith / Langfuse tracing | **不重叠**：那是可观测性，本插件是合规审计（append-only、有裁决人） |
| `Skill` 的 `security_scanner` | **不重叠**：那是 skill 内容的 LLM 安全分类，本插件是运行时工具调用授权 |

一句话：**能用官方扩展点就不写新中间件，官方已经做了的就不做第二遍。**
