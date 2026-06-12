# Anthropic Claude Code Skills 最佳实践（结构化总结）

> 来源：https://claude.com/blog/lessons-from-building-claude-code-how-we-use-skills
> 原文标题：*Lessons from building Claude Code: How we use skills*
> 作者：Thariq Shihipar（MTS @ Anthropic, Claude Code）
> 原文发布：2026-06-03 ｜ 总结整理：2026-06-09
> 阅读时长：5 分钟
> 用途：优化本项目 `skills/public/` 与 `skills/custom/` 下的 skill 时作为参考基线

---

## 0. 文章核心论点

> Skills 已经是 Claude Code 中最常用的扩展点之一（flexible、easy to make、easy to distribute），但灵活性也让人难以判断"什么值得做、怎么结构化、何时分享"。Anthropic 内部有几百个活跃 skill，本文是他们总结的"加速开发"经验。

三条反复出现的判断标准：

1. **一个 skill 只做一件事** —— 最好的 skill 干净地落在某一个分类里；试图同时干几件事的 skill 反而让 agent 困惑。
2. **Gotchas 才是高信号** —— 最高价值的部分不是知识陈述，而是 Claude 在使用这个 skill 时反复踩到的坑。
3. **最佳 skill 几乎都从几行 + 一个 gotcha 起步** —— 边用边补，而不是一次写对。

---

## 1. What are skills? —— 先正名

⚠️ **常见误解**：很多人以为 skill "just markdown files"。

实际定义：

- skill 是**一个文件夹**（不是单文件）
- 里面可以放：指令、**脚本**、**资源 / 素材**、**数据**
- agent 可以主动 **discover / explore / manipulate** 这个目录
- 在 Claude Code 里还有大量配置选项，**包括注册动态 hooks**
- 真正有效的 skill 通常都**充分利用了目录结构和这些配置选项**，而不是只写一段说明

> 关键词：**文件夹 = context engineering 的一种形态**（后文多次回到这一点）。

---

## 2. Types of skills —— 9 大分类（全文最重的一节）

> 来源说明：Anthropic 把所有内部 skill 整理归类后，自然聚成 9 个 bucket。**这不是定论，但作为发现"自己 skill 库缺什么"的框架很有用**。

| # | 分类 | 核心作用 | 典型例子（原文给出） |
|---|---|---|---|
| 1 | **Library and API reference** 库与 API 参考 | 教 Claude 正确使用某个 library / CLI / SDK（含内部库和 Claude 处理不好的常见库） | `billing-lib`（内部计费库的边界 & 陷阱）<br>`internal-platform-cli`（每个子命令 + 使用时机）<br>`sandbox-proxy`（公司 egress 网关：哪些 host 可达、连接拒绝怎么 debug、怎么加白名单） |
| 2 | **Product verification** 产品验证 | 描述怎么测试 / 验证代码，常配合 playwright、tmux 等外部工具 | `signup-flow-driver`（headless 浏览器走完注册→邮箱验证→onboarding，每步 hook 断言状态）<br>`checkout-verifier`（用 Stripe 测试卡驱动 checkout UI，验证 invoice 落到正确状态）<br>`tmux-cli-driver`（需要 TTY 的交互式 CLI 测试） |
| 3 | **Data fetching and analysis** 数据获取与分析 | 连接数据 / 监控栈，携带凭证、dashboard id、常用 workflow | `funnel-query`（"signup→activation→paid 关联哪些事件"，并指出哪张表才是真正的 user_id）<br>`cohort-compare`（对比两个 cohort 留存/转化，标统计显著差，附 segment 定义）<br>`grafana`（datasource UID、集群名、症状→dashboard 查找表）<br>`datadog`（字段名差异，如 `@request_id` vs `trace_id`、service 列表、metric 前缀约定） |
| 4 | **Business process and team automation** 业务流程与团队自动化 | 把重复 workflow 收敛成一个命令；可能依赖其它 skill 或 MCP | `standup-post`（汇总工单系统 + GitHub 活动 + 昨日 Slack，输出 standup，**只输出 delta**）<br>`create-<ticket-system>-ticket`（强制 schema + 创建后工作流：通知 reviewer、贴 Slack）<br>`weekly-recap`（merged PRs + closed tickets + deploys → 格式化 recap） |
| 5 | **Code scaffolding and templates** 代码脚手架与模板 | 给特定功能生成框架 boilerplate；可与可组合脚本配合 | `new-<framework>-workflow`（带你们注释的新 service/workflow/handler）<br>`new-migration`（迁移文件模板 + 常见坑）<br>`create-app`（带你们 auth、logging、deploy 配置的新内部 app） |
| 6 | **Code quality and review** 代码质量与评审 | 强制组织内的代码规范与 review 流程 | `adversarial-review`（派 fresh-eyes subagent 挑刺 → 实现修复 → 反复迭代直到只剩 nitpick）<br>`code-style`（强约束 Claude 默认做不好的 style）<br>`testing-practices`（写测试的方法与边界） |
| 7 | **CI/CD and deployment** 持续集成与部署 | 拉取、推送、部署；可能引用其它 skill 收集数据 | `babysit-pr`（监控 PR → 重试 flaky CI → 解决 merge 冲突 → 开 auto-merge）<br>`deploy-<service>`（build → smoke test → 灰度放量 + 错误率对比 → 异常自动回滚）<br>`cherry-pick-prod`（隔离 worktree → cherry-pick → 解冲突 → 出带模板的 PR） |
| 8 | **Runbooks** 运维手册 | 给定症状（Slack 帖、告警、错误签名），跨工具排查后输出结构化报告 | `<service>-debugging`（症状→工具→查询模式，针对高流量服务）<br>`oncall-runner`（拉告警 → 查常见嫌疑 → 输出 finding）<br>`log-correlator`（给一个 request id，从所有可能碰过它的系统拉匹配日志） |
| 9 | **Infrastructure operations** 基础设施运维 | 例行维护和操作流程，含**可能具有破坏性的动作**（因此需要护栏） | `<resource>-orphans`（找孤立 pod/volume → 发 Slack → soak 期 → 用户确认 → 级联清理）<br>`dependency-management`（组织内依赖审批 workflow）<br>`cost-investigation`（"为什么存储/egress 账单突然涨"，含具体 bucket 和查询模式） |

### 2.1 作者最看重的一条洞察

原文（出自第 2 类）：

> "Verification skills have had the **most measurable impact** on Claude's output quality internally. **It can be worth having an engineer spend a week just making your verification skills excellent.**"

翻译：验证类 skill 内部数据显示对输出质量影响最大；值得派一个工程师花一整周把验证类 skill 做到极致。

### 2.2 5 个藏在分类描述里的小技巧

- 验证类可以**让 Claude 录视频**让你看到它到底测了什么
- 验证类可以**强制每步做程序化断言**（assert state at each step）
- 业务类 skill 可以**把历史结果存到日志文件**，让模型下次跑能"读自己历史"并保持一致性
- 代码质量类可以**用 hook 或 GitHub Action 自动跑**
- 运维类因为有破坏性动作，**特别需要护栏**（guardrails）

---

## 3. Tips for making skills —— 8 条制作最佳实践

这一节是文章中段精华。每条都给出"做法 + 反例/正例"。

### 3.1 Don't state the obvious —— 不要讲 Claude 已经知道的事

- Claude 本来就会写代码、会读 codebase
- 重述它"本来就会做"的事 = **只加 context、不加 value**
- 真正"推它出默认行为"的 skill 才有价值
- **正例**：*frontend design skill* —— 由一位工程师与客户多轮迭代，专门用来**打破 Claude 的默认设计倾向**（例如 Inter 字体、紫色渐变）

### 3.2 Build a gotchas section —— 写"踩坑清单"

- **最高信号内容就是 Gotchas 一节**
- 应基于"Claude 用你这个 skill 时反复撞到的失败点"持续累积
- **正例**（原文给了 3 条真实的 gotcha 写法）：
  > "The subscriptions table is append-only. The row you want is the one with the highest **version**, not the most recent **created_at**."
  > "This field is called `@request_id` in the API gateway and `trace_id` in the billing service. They're the same value."
  > "Staging returns 200 even when the Stripe webhook didn't actually process. Check `payment_events` for the real state."

### 3.3 Use the file system and progressive disclosure —— 用文件系统做渐进式披露

- SKILL.md 是入口，**指向其它文件供特定情况加载**
- 把整个目录树看作 context engineering 的一种形态
- **最简单的 progressive disclosure**：在 SKILL.md 指向其它 markdown
  - 例：详细函数签名和使用例放 `references/api.md`
- **模板式 progressive disclosure**：如果产物是 markdown，把模板放 `assets/` 让 Claude 复制使用
- 你可以建立 references / scripts / examples 等子目录

### 3.4 Avoid railroading Claude —— 别把 Claude 钉死

- 因为 skill 会被大量复用，**指令太具体反而有害**
- 原则："给信息，留余地"
- 让它能 adapt 到具体场景

### 3.5 Think through the setup —— 设计用户设置流程

- 有些 skill 需要用户提供上下文（如把 standup 发到哪个 Slack channel）
- 推荐做法：把这类配置存到 skill 目录下的 **`config.json`**
- 启动时如果 config 没配好，**agent 反过来问用户**
- 想要结构化多选 → 让 agent 用 **AskUserQuestion tool**

### 3.6 Write descriptions for the model, not for humans —— 描述写给模型看

- Claude Code 启动时会**为每个 skill 构造一条 description listing**
- Claude 靠这段 description 决定"这个请求有没有合适的 skill"
- 所以 description 不是给人读的 summary，**而是触发条件的描述**
- **关键技巧**：在 description 里**嵌入触发词**
  - 例：babysit 类型的 skill，description 里加 "babysit" 这个词

### 3.7 Help Claude remember —— 给 Claude 留"记忆"

- skill 可以在自己的目录里存储数据，形成**自带的轻量 memory**
- 形式不限：append-only 文本日志、JSON、SQLite 都行
- **正例**：`standup-post` skill 维护 `standups.log`，每次都把"自己写过的历史"读出来，对比后输出 delta
- 路径变量：环境变量 **`${CLAUDE_PLUGIN_DATA}`** 指向一个稳定目录用于持久化数据（官方文档见 *plugins-reference#persistent-data-directory*）

### 3.8 Store scripts and generate code —— 提供脚本让 Claude 即兴编排

- "给 Claude 代码"是**最强大的工具之一**
- 用意：让 Claude 把 turns 花在"组合与决策"上，而不是重写 boilerplate
- **正例**：data-science skill 里给一个事件源数据获取的函数库，Claude 现场拼出脚本回答"What happened on Tuesday?"

### 3.9 Use on-demand hooks —— 按需挂 hook

- skill 可以带 hook，**只在被调用时激活，且只在该 session 持续期间有效**
- 适用场景：观点很强、但**不希望默认全局开** 的 hook
- **正例**：
  - `/careful`：在 Bash 的 PreToolUse 上拦 `rm -rf`、`DROP TABLE`、`force-push`、`kubectl delete`。只在确认在动 prod 时开，常开会疯
  - `/freeze`：拦任何 Edit/Write 不在指定目录内。debug 时常用——"我只想加日志，老是不小心'修'无关代码"

---

## 4. Distributing skills —— 分发方式

两种主要分发路径：

1. **Check in 到 repo**：放 `./.claude/skills`
   - 适合**小团队 + 少量 repo**
   - **代价**：每个被 check in 的 skill 都会给模型 context 加一点点负担
2. **做成 plugin，进入 plugin marketplace**
   - 适合规模化
   - 用户自己选择装哪些、带 setup 流程
   - 官方文档见 *plugins-reference*

---

## 5. Managing a skills marketplace —— 市场怎么管

- Anthropic **没有中央团队决定** 哪些 skill 进市场
- 流程：
  1. 任何作者可以把 skill 上传到 GitHub 的 sandbox 文件夹，并在 Slack 等渠道推荐
  2. 当 skill 获得足够 traction（**由 owner 自己判断**）
  3. 作者提 PR，把 skill 移到 marketplace
- 关键词：**organic adoption**（自然增长），**owner 主导**

---

## 6. Composing skills —— skill 之间如何组合

- 例：上传文件的 skill + 生成 CSV 并上传的 skill
- **市场与 skill 本身目前还没有原生的依赖管理**
- **当前 workaround**：用名字引用其它 skill，**模型在它们已安装时会自动 invoke**

---

## 7. Measuring skills —— 怎么衡量 skill 表现

- 用一个 **PreToolUse hook** 记录 skill 使用情况
- 官方给了 example code（见原文链接）
- 用途：
  - 找出"**popular**" skill
  - 找出"**undertriggering**"（本应被触发但实际很少被触发）的 skill

---

## 8. Get started —— 收尾态度

- skill 最佳实践**仍在演进**
- 几乎所有最佳 skill 都是**从几行 + 一个 gotcha 起步**，靠边用边补
- 三条 call-to-action：
  1. 看 skills 文档
  2. 找现成 example skill 改一改
- 作者署名：**Thariq Shihipar, MTS @ Anthropic, Claude Code**

---

## 9. 落地行动表（针对本项目 skill 优化）

> ⚠️ 改 skill 前先看 `skills/public/` 同类 sibling skill 的现有约定，再做改动。

| # | 行动 | 依据文章哪一节 |
|---|---|---|
| 1 | 给每个现有 skill 做 9 类打标，找出"跨类"或"不知道归哪儿"的 candidate | §2 Types of skills |
| 2 | 给每个 skill 强制加一个 **Gotchas** 段落（哪怕只有 1 条） | §3.2 |
| 3 | 检查 description 是否写成"**触发条件**"而非"摘要" | §3.6 |
| 4 | 把高重复 workflow 收敛成一个 skill（standup / recap / ticket） | §2 第 4 类 |
| 5 | 优先投资 **verification 类** skill（"花一周把验证做透"） | §2.1 内部结论 |
| 6 | 评估是否要把 skill 从 repo 迁到 plugin marketplace（看团队规模） | §4 |
| 7 | 在 PreToolUse hook 上加 skill 使用埋点，找 popular / undertriggering | §7 |
| 8 | 引入 `${CLAUDE_PLUGIN_DATA}` 做轻量记忆（log / json / sqlite） | §3.7 |

---

## 10. 一句话压缩

> Skill 是一个可被 agent 主动探索的文件夹；好 skill 只做一件事、把"踩坑清单"当宝贝、用目录树做渐进披露、用 description 写触发条件而不是摘要；最有杠杆的是 verification 类和把重复 workflow 收敛成一键执行的流程类；规模上去就用 plugin marketplace + PreToolUse 埋点来治理。
