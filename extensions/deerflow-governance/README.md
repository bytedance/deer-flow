# deerflow-governance · DeerFlow 生产治理插件

给 [DeerFlow 2.0](https://github.com/bytedance/deer-flow) 补上三件生产环境跑不掉、但框架本身没做的事：

| 能力 | DeerFlow 现状 | 本插件补什么 |
|---|---|---|
| **人工审批** | `GuardrailProvider` 只有 allow / deny 两态 | 补第三态 **ask**：挂起、开审批单、人批完再放行 |
| **合规审计** | 有 `SandboxAuditMiddleware` 和 LangSmith/Langfuse 链路追踪 | 补**面向合规的决策账本**：策略判定 → 开单 → 裁决人 → 结论，append-only 可导出 |
| **成本治理** | `TokenBudgetMiddleware` 管单 run 的 token；`SubagentLimitMiddleware` 管并发数 ≤ 3 | 补 **run/thread/day 三层 × 五维度**（token、金额、工具调用、委派次数、墙钟）+ 预警/熔断两级阈值 |

**零侵入**：不改 DeerFlow 一行代码。审批走官方的 `guardrails.provider.use` 反射加载点，
预算走 `build_middlewares(custom_middlewares=[...])` 官方注入点。

## 30 秒看懂它做什么

```
[放行] 主Agent → bash: pytest tests/ -q                    规则 bash-default
[拦截] 主Agent → bash: rm -rf /data/prod                   规则 bash-destructive（critical，直接拒绝，不给审批机会）
[挂起] 主Agent → bash: git push origin main                规则 bash-credentials-or-push → 开单 APR-2CB10E4AC1

  $ governance approve APR-2CB10E4AC1 --by 张三 --note "已确认目标分支"

[放行] 主Agent → bash: git push origin main                已由 张三 批准
[拦截] 主Agent → bash: git push origin --force main        exact 授权不外溢，--force 是另一次操作

[放行] 主Agent  → bash: ls -al                             常规 shell
[挂起] 子Agent → bash: ls -al                              同一条命令，子 Agent 更严（用户看不到它的中间过程）
```

预算：

```
第 3 轮  tokens=162000  调用=66  委派=6  成本=¥0.4320  →  WARN
         [预算预警] 本次运行的子 Agent 委派次数已用 6 / 8（75%）。请收敛策略：优先完成主线…
第 4 轮  tokens=216000  调用=88  委派=8  成本=¥0.5760  →  STOP
         [预算熔断] 本次运行的子 Agent 委派次数已达上限（8 / 8），本轮停止继续调用工具…
```

## 快速开始

```bash
pip install -e .                       # 或直接 PYTHONPATH=src
cp governance.example.yaml governance.yaml
export DEERFLOW_GOVERNANCE_CONFIG=$PWD/governance.yaml

make test                              # 47 个用例，不需要 DeerFlow / API key
make demo                              # 端到端演示全部场景
governance validate                    # 校验策略配置（可进 CI）
governance simulate --tool bash --arg command="rm -rf build" --explain   # 干跑，上线新规则前必做
```

接进 DeerFlow：见 [docs/INTEGRATION.md](docs/INTEGRATION.md)（两处配置，不改源码）。
设计取舍与源码依据：见 [docs/DESIGN.md](docs/DESIGN.md)。

## 架构

```
交付面     cli.py（审批/审计/预算/干跑）
                    │
适配层     provider.py            middleware.py          ← 唯一 import DeerFlow / langchain 的两个文件
           GuardrailProvider      AgentMiddleware
                    │                    │
核心层     engine.py（审批状态机）  budget.py（分层账本+熔断）
           policy.py（规则引擎）    pricing.py（金额口径）
           fingerprint.py（指纹）   store.py（SQLite 单据+审计）
                    └──────── contracts.py（唯一语义真源） ────────┘
```

**核心层零三方依赖**（只用 stdlib + PyYAML 读配置），所以 47 个用例和端到端演示
能在**没装 DeerFlow、没装 langchain、没有 API key** 的机器上完整跑完。
适配层刻意写得很薄：字段搬运 + 结果翻译，不含任何判断。

## 审批模式

| 模式 | 机制 | 适用 | 状态 |
|---|---|---|---|
| `ticket`（默认） | 开单 → 本次拒绝并告知单号 → 人批 → 重试放行 | 主 Agent 与**子 Agent 都可用** | 已离线验证 |
| `interrupt` | 调 LangGraph `interrupt()` 真正挂起 | 只能用于主 Agent | **未实测**，见 INTEGRATION.md |

选 `ticket` 作默认的理由：DeerFlow 的子 agent 图是 `checkpointer=False` 编译的
（AGENTS.md 原文："subagents are one-shot and never resume"），
子 agent 里 `interrupt()` 不成立；而恰恰是子 agent 最需要审批 —— 它的中间过程用户看不见。

## 已知边界

- 预算账本默认在**内存**里，进程重启清零。跨进程的日配额需要注入 `CounterBackend`（接口已留，未提供 SQLite 实现）。
- 价目表是**可覆盖的默认值不是事实**，上线前必须核对各家官方价目页；未知模型成本记 `unknown` 而非 0。
- 策略是**规则匹配**不是语义理解，`bash: python -c "import os;os.system('rm -rf /')"` 这类嵌套绕过拦不住 —— 真正的隔离边界是沙箱，本插件是沙箱之上的审批层，不是替代品。
- 引用 DeerFlow 内部符号（`GuardrailRequest` 字段、`build_middlewares` 签名）会随上游演进，锁定的版本见 INTEGRATION.md。
