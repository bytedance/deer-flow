---
name: chinese_official_writing
description: 用于起草、改写和复核中文公文及正式工作材料；当用户要求通知、请示、报告、函、复函、批复、意见、决定、决议、议案、公报、命令、公告、通告、公示、通报、纪要、方案、说明、申请、征求意见函、采购公告、可研、调研、总结、工作要点、审查材料、讲话稿、致辞、述职报告等中文正式文本，或需要顺稿、压缩、去口语化、降 AI 味、文种校验、办理要素核对时使用。不用于英文、文学、营销、社媒、批量语料或替代法律/财务/采购/审计判断。
license: MIT-0
metadata:
  version: "1.2.28"
  compatible_agents:
    - codex
    - claude-code
    - openclaw
    - hermes
    - qwen-code
    - kimi-code
    - generic-skill-md-agent
  qwen_code:
    install_personal: "~/.qwen/skills/chinese-official-writing"
    install_project: ".qwen/skills/chinese-official-writing"
    entry: "SKILL.md"
  kimi_code:
    skills_dir: "copy folder or pass with --skills-dir"
    invocation: "/skill:chinese-official-writing"
    entry: "SKILL.md"
  openclaw:
    version: "1.2.28"
    emoji: "📝"
    tags:
      - chinese
      - official-document
      - writing
      - gongwen
      - ai-compute
---

# 中文公文写作 Skill

让你的 AI Agent 写出更像正式公文的请示、报告、通知、方案和讲话稿：文种不乱、行文关系不乱、办理要素不漏，尽量减少 AI 腔。

装上后，你可以直接说：

- “帮我起草一份项目请示”：按一文一事、请批事项、依据和请批语组织正文。
- “审查这份方案有没有 AI 味”：检查旁白式写法、教学腔、口语化判断和二元包装句。
- “写一份 AI 算力租赁方案”：按需求来源、Token/资源测算、成本边界、SLA、安全和验收组织正文。
- “把这份报告压缩到 800 字”：顺稿、去重、去口语化，同时保留关键办理要素。

覆盖 27+ 种中文正式文种。不用于文学创作、营销文案、社交媒体贴文、英文写作、批量语料生成或规避人工审核。法律、财务、采购、审计和正式签发结论仍需人工复核。

## 安装

```bash
clawhub install chinese-official-writing
```

其他平台如 Codex、Claude Code、Hermes、deepseek-tui 的安装 Prompt，请看 GitHub 仓库 README：
https://github.com/gongyu0918-debug/chinese-official-writing-skill

当前版本：`chinese-official-writing@1.2.28`

ClawHub 页面只展示摘要；安装包内的 `SKILL.md` 和 `references/` 保留完整规则、硬边界和复核清单。

## 适用场景

| 你需要的 | 直接说 |
| --- | --- |
| 法定公文 | 通知、请示、报告、函、批复、意见、决定、公告、通告、通报、纪要等 |
| 事务材料 | 方案、可研、总结、调研报告、讲话稿、致辞、述职报告 |
| 技术材料 | AI 算力可研、GPU/服务器租赁、SLA 保障、成本对比 |
| 审稿润色 | 顺稿、压缩、去口语化、降 AI 味、格式核验 |

## 核心能力

### 起草

- 文种路由：判断该用请示、报告、通知、函还是其他文种。
- 办理要素核对：检查主体、对象、事项、时限、附件、反馈渠道是否齐全。
- 论证链条：按文种组织正文逻辑，请示先写请批事项，方案先写目标任务。
- 视角控制：从发文单位、报告单位或项目单位视角写，不写成教程。

### 审稿

- 低 AI 味审查：检查旁白句、教学腔、二元包装句和口语化判断。
- 重复事项检测：提示相邻段落换词重复、胶水段落和空泛套话。
- 标题核验：检查正文是否跑题，标题是否漂移或过度承诺。
- 交付完整性：检查落款、日期、用户指定事项和未完成占位是否处理干净。

### 算力和租赁材料

- 按“需求来源 -> Token/资源测算 -> 成本边界 -> SLA/安全/验收”组织材料。
- 不写技术空话，每项成本和服务要求尽量落到业务场景、边界和验收。

## 快速试用

```text
起草一份关于举办中小学人工智能教师培训的请示。要求一文一事，写清经费来源，结尾使用“妥否，请批示。”
```

```text
审查这份建设方案，指出文种错位、视角错位、AI 腔、重复事项和未完成占位。
```

```text
起草一段算力资源租赁技术服务需求，写清并发、SLA、数据安全、费用上限和验收指标，不指定品牌和型号。
```

## 质量保证

经 270 条合成反例消融测试，使用本 Skill 后，高中低风险从 Baseline 的 1594 降至 1。完整评测方法、测试脚本和多平台安装说明见 GitHub 仓库。

## 反馈

- 问题和建议：https://github.com/gongyu0918-debug/chinese-official-writing-skill/issues
- ClawHub 页面：https://clawhub.ai/gongyu0918-debug/chinese-official-writing

## License

MIT-0

## Gotchas（高频陷阱速查）

> 这些是 Claude 在起草中文公文时**反复踩到的**硬陷阱，**优先级高于风格选择**。起草和复核时先扫一遍本节。

1. **`"妥否，请批示"` 不是请示的专利**：先看标题、接收对象、申请事项和用户模板，**别只看结尾语判定文种**。申请、汇报、向上级请求批准都可以用它。
2. **不要把企业/内部申请强行改成法定公文格式**：可能是"单位名称 + 申请标题"两行标题 + `尊敬的领导：` + 字段式费用明细 + 右下落款。用户提供真实模板时**保留模板骨架**。
3. **思考泄露硬删**：`作为 AI…`、`我的思路是…`、`接下来我会…`、`按你的要求修改如下…` 等起草过程话术**不能进正式正文**。
4. **空话套话要有支撑**：`持续推进`、`全面赋能`、`形成闭环`、`有力支撑` —— 没对象/责任/时限/数据/办理动作时**就是套话**，应改具体工作。
5. **算力/GPU 材料的"自主可控"必须落地**：部署边界、数据位置、权限、密钥、日志、审计措施 —— 缺这些就掉 AI 味。
6. **不要编造政策依据、数字、日期、联系人、文号、会议结论** —— 任何硬边界事实绝不补造，缺项在正文外提示用户。

## Agent 使用规则

安装后执行写作任务时，仍按以下规则处理：

1. 先判断文种，再抽取办理要素，再选择论证链条，最后进入语言和格式复核。
2. 文种判断以官方规范和 `references/genre-routing.md` 为准；社区模板不得替代文种功能。
3. 起草前按 `references/handling-elements.md` 核对发文主体、受文对象、事项、依据、时限、责任、附件、反馈渠道和请批事项。
4. 成文时按 `references/argument-chains.md` 组织段落，每段服务一个论点，通常按“结论前置、事实支撑、判断归纳、事项落点”展开。
5. 从发文单位、报告单位、项目单位或主管单位视角写，不使用旁观者、教师或评论员口吻。
6. 数据和判断要可追溯；不编造实际数据，测算和预估必须标明性质。
7. 起草算力、采购、租赁或服务器租赁材料时，论证重点放在需求来源、Token/资源换算、成本比较、SLA、并发、安全、交付和验收。
8. 最终正文不得残留 `〔签发日期〕`、`〔会议时间〕`、`〔待补充〕`、`[具体项目名称]`、`XXXX万元`、`YYYY年MM月DD日`、`（签发日期）` 等未完成占位；缺项在正文外提示用户确认。当前日期只可用于草稿落款，不得替代维护时间、会议时间、实施期限、政策依据或业务数据。
9. 检查 `.txt`、`.md` 或 `.docx` 草稿时，可使用 `scripts/prose_lint.py`。脚本只提示风险，不自动改写。

## References 速查

> 完整内容在各 reference 文件。**起草时不要一次性全部加载**；按 `references/workflow.md` 的"明确任务口径"步骤，按需读取。

| 文件 | 一句话定位 |
| --- | --- |
| `references/workflow.md` | 起草前先形成"文稿蓝图"（文种/行文关系/视角/对象/核心结论/材料顺序/数据状态） |
| `references/genre-routing.md` | 文种不清/标题内容不一致时**先读**；以法定功能/行文关系/办理需求为准 |
| `references/handling-elements.md` | 起草前核对办理要素（主体/对象/事项/依据/风险/请求/时限） |
| `references/argument-chains.md` | 段落组织：主要事项→事实依据→问题/风险→安排/请求/责任；一段一判断 |
| `references/official-style.md` | 语言风格与视角选择；**全文保持同一视角**（发文/报告/项目/企业/调研之一） |
| `references/genre-checklist.md` | 27+ 文种功能与办理要素清单；不要把所有任务写成泛"正式材料" |
| `references/formal-addressing.md` | 称谓/敬语/谦辞/结尾语核对；上行文/下行文/平行文区分；不知道时用中性称谓 |
| `references/format-gbt9704.md` | GB/T 9704-2012 公开国标版式核对点；用户未要求时不主动补版头/文号/印章/日期 |
| `references/anti-ai-patterns.md` | 反 AI 表达检查：模板腔/教学腔/口语化/空泛技术表述的句式与词汇 |
| `references/ai-compute-docs.md` | AI 算力/技术服务材料专用；通用公文**不应默认加载** |
| `references/final-review-layers.md` | 三层复核：硬边界优先→质量建议其次→场景资料按需读取 |
| `references/review-checklist.md` | 段落/小节/全文复核**执行清单**；具体规则跳转到其他 reference |
| `scripts/prose_lint.py` | 草稿定稿前的程序化检查（AI 味、口语化、未完成占位） |
