# chatbi-report 计算与描述 checkpoint 设计

日期：2026-06-27

## 背景

`chatbi-report` 目前已有两个用户 checkpoint：Step 1.5 lint 复核和 Step 3.5 SQLBot 取数复核。用户确认取数后，流水线会继续生成计算代码、校验并执行计算列、生成描述段落，并直接渲染最终报表，中间没有新的用户复核点。

本次变更在计算列合并完成后、描述生成完成后各增加一个用户确认点。目标是在最终渲染前，让用户先确认将进入描述生成的数据，以及最终会写入报表的描述文本。

## 目标

- 计算完成后展示计算列结果，无论全部成功、部分失败还是全部失败。
- 在进入描述生成和最终渲染前询问用户是否继续。
- 最终渲染前展示已生成的描述段落。
- 如果用户不满意描述，停止流水线，并提示用户修改原始样张里的 `> 描述:` 块后重跑。
- 保持现有自动重试预算和 sentinel 行为不变。

## 非目标

- 不增加 Step 6.5 IR preview checkpoint。IR 只能展示计划中的计算 spec，无法展示 codegen、validate、evaluate 或最终 sentinel 结果。
- 不支持本次运行内编辑 prompt 或临时覆盖 Step 8d prompt。
- 不自动修改用户上传的原始样张。

## 更新后的流水线

当前尾部流程：

```text
6 extract-ir → 7 codegen → 8a validate → 8b evaluate → 8c apply-computed → 8d describe → 9 render/status
```

新的尾部流程：

```text
6 extract-ir
→ 7 codegen
→ 8a validate
→ 8b evaluate
→ 8c apply-computed
→ 8c.5 compute checkpoint
→ 8d describe
→ 8d.5 description checkpoint
→ 9 render/status
```

两个新增步骤都是 `agent-turn-checkpoint`，沿用现有 `ask_clarification(question, clarification_type, context, options)` 契约，`clarification_type` 继续使用 `risk_confirmation`。

## Step 8c.5 compute checkpoint

### 触发条件

Step 8c 完成后，如果计算 spec 总数大于 0，则总是触发，不受成功数或失败数影响。

如果样张没有任何计算列，即 `total = 0`，则静默跳过 Step 8c.5，直接进入 Step 8d 或 Step 9。

### 展示给用户的内容

展示一段简洁摘要，包含：

- 计算 spec 总数、成功数、失败数。
- 失败计算列名称和失败原因，如有。
- 每个 report 前 2 行的计算列值预览。
- 明确说明：如果带失败继续，最终报表会保留 `⚠️COMPUTE_FAILED`，最终状态可能是 `partial`。

### question 与 options

至少一个计算列成功时：

```text
计算列处理完成：{ok}/{total} 成功。是否继续生成描述和最终报表？
```

选项：

```text
["继续", "停下（我去修计算定义）"]
```

全部计算列失败时：

```text
计算列全部失败：0/{total}。是否继续用 ⚠️COMPUTE_FAILED 占位生成 partial 报表？
```

选项：

```text
["继续（partial，用 ⚠️COMPUTE_FAILED 占位）", "停下（我去修计算定义）"]
```

### 用户选择继续

追加 runlog：

```text
Step 8c.5 checkpoint: confirmed, ok={ok}, total={total}
```

然后进入 Step 8d。

### 用户选择停下

追加 runlog：

```text
Step 8c.5 checkpoint: aborted by user, ok={ok}, total={total}
```

写入 status：

- `status = error`
- `exit_step = 8c.5`
- `error_class = USER_ABORTED`
- `error_detail` 包含计算 checkpoint 摘要，以及下一步动作：修改原始样张里的 `> 计算:` 块后重跑。

随后按现有最终回复模板收口。

## Step 8d 与 8d.5 description checkpoint

### Step 8d 生成行为

Step 8d 继续读取：

- `prompts/description_gen.md`
- `<stem>.wide.json`
- parsed 中从样张 `> 描述:` 块解析出的每个 report 的 `description_prompt`

它为每个带 `> 描述:` 块的 report 生成一段描述，并写入现有精确输出路径：

```text
/mnt/user-data/outputs/<stem>.description.report-<idx>.txt
```

现有失败处理保持不变：每个 report 最多自动重新生成一次；仍失败时，描述文件写入 `⚠️DESCRIPTION_FAILED`，流水线继续进入 checkpoint 复核。

### Step 8d.5 触发条件

只要样张中存在至少一个 `> 描述:` 块，就总是触发。没有描述需求时静默跳过。

### 展示给用户的内容

对每个已生成描述的 report 展示：

- report 标题。
- 原始 `> 描述:` prompt。
- 生成的描述文本；如果生成失败，则展示 `⚠️DESCRIPTION_FAILED`。

### question 与 options

```text
描述段落已生成：{ok}/{total} 成功。是否满意并继续渲染最终报表？
```

选项：

```text
["满意，继续", "不满意，停下修改描述提示词"]
```

### 用户选择继续

追加 runlog：

```text
Step 8d.5 checkpoint: confirmed, ok={ok}, total={total}
```

然后进入 Step 9。

### 用户选择停下

追加 runlog：

```text
Step 8d.5 checkpoint: aborted by user, ok={ok}, total={total}
```

写入 status：

- `status = error`
- `exit_step = 8d.5`
- `error_class = USER_ABORTED`
- `error_detail` 包含描述 checkpoint 摘要，以及下一步动作：修改原始样张里的 `> 描述:` 块后重跑。

同一次运行内不接受新 prompt 重新生成，也不回写上传的样张。

## 重试与 sentinel 语义

现有自动重试预算保持不变：

- Step 8a validate：每个 spec 校验失败后最多重新 codegen 一次；仍失败则写入 `⚠️COMPUTE_FAILED` 并继续。
- Step 8d describe：每个 report 描述生成失败后最多重新生成一次；仍失败则写入 `⚠️DESCRIPTION_FAILED` 并继续。

新增 checkpoint 是用户决策点，不是 retry loop。用户选择停下时，本次运行以 `USER_ABORTED` 结束；用户选择带 sentinel 继续时，最终状态可能是 `partial`。

## 输出产物职责边界

本次变更需要重新明确 `report.md` / `report.docx`、对话进度、`runlog.md`、`status.json` 的职责边界。

### 面向用户的输出

用户真正需要消费的是：

- 每步完成后的中文进度反馈。
- checkpoint 时展示的中文摘要、问题和选项。
- 最终回复里的中文状态总结、关键指标和下一步建议。
- 最终交付物 `report.md` / `report.docx`。

因此，最终回复不再强制列出 `runlog.md` 和 `status.json` 路径，也不直接粘贴 `status.json` 原文。

### `<stem>.runlog.md`

`runlog.md` 定位为内部运行台账和排障材料，不是普通用户交付物。

它仍然需要保留，用于：

- Agent 恢复上下文时复盘执行过程。
- partial / error 排障时追踪每一步发生了什么。
- 记录 checkpoint 的用户选择，形成审计记录。

如果继续使用 Markdown 格式，内容应改为中文优先，例如：

```text
- Step 8c.5 计算 checkpoint：用户确认继续，成功=2，总数=3
```

`runlog.md` 默认不在最终回复中作为用户产物展示；只有用户要求排查，或需要定位异常时，才提示其内部路径。

### `<stem>.status.json`

`status.json` 定位为 Agent / 编排器 / 自动化流程读取的机器契约，不面向人类直接展示。

它用于结构化记录：

- `status = success | partial | error`
- `exit_step`
- `error_class`
- `error_detail`
- `outputs`
- `metrics`

Agent 最终回复应读取 `status.json`，把关键字段转成中文摘要给用户，而不是把 JSON 原文或路径当作交付物展示。

新增 checkpoint 时：

- `runlog.md` 记录“发生了什么”和“用户怎么选”。
- `status.json` 记录“最终停在哪一步”和“机器如何分类这次运行”。
- 对话消息负责把这些信息转成人类可理解的中文反馈。

## 文档更新范围

更新 `skills/public/chatbi-report/SKILL.md` 的以下部分：

- 状态机：加入 `8c.5 compute checkpoint` 和 `8d.5 description checkpoint`。
- 步骤类型：把新增 checkpoint 纳入 `agent-turn-checkpoint`。
- 步骤定义表：增加 8c.5 和 8d.5 两行。
- Checkpoint 通用契约：覆盖 1.5、3.5、8c.5、8d.5。
- 新增 Step 8c.5 和 Step 8d.5 专属小节。
- 重试预算：说明 checkpoint 不属于自动重试预算。
- 进度反馈：新增 8c.5 和 8d.5 反馈文案。
- 数字提取来源：新增 8c.5 和 8d.5 的计数来源。
- 失败处理：补充 8c.5 和 8d.5 checkpoint 停下的行为。
- status schema：允许 `exit_step = 8c.5 | 8d.5`。
- 输出呈现：明确 `report.md` / `report.docx` 是用户交付物，`runlog.md` 是内部运行台账，`status.json` 是机器契约；最终回复不再强制展示 `runlog.md` / `status.json` 路径。
- 最终回复说明：checkpoint 停下可能发生在 1.5、3.5、8c.5 或 8d.5，回复需给中文摘要和下一步建议。

## 脚本与测试更新范围

主要行为由 `SKILL.md` 约束，但配套脚本和测试可能需要同步：

- 如果 `assemble_status.py` 校验 `exit_step`，需要允许 `8c.5` 和 `8d.5`。
- `assemble_status.py` 测试需要覆盖 `USER_ABORTED` at 8c.5 和 8d.5。
- 如果已有测试断言状态机、进度文案或允许的 `exit_step`，需要同步更新。

## 验收标准

- 带计算列的运行在 Step 8c 后总是暂停，并在 Step 8d 前展示计算成功/失败摘要。
- Step 8c.5 选择继续会进入描述/渲染；选择停下会写入 `USER_ABORTED`，且 `exit_step = 8c.5`。
- 带 `> 描述:` 块的运行在 Step 8d 后总是暂停，并在 Step 9 前展示生成的描述。
- Step 8d.5 选择继续会渲染最终产物；选择停下会写入 `USER_ABORTED`，且 `exit_step = 8d.5`，并提示用户修改原始 `> 描述:` 块后重跑。
- 用户选择继续时，现有 `⚠️COMPUTE_FAILED` 和 `⚠️DESCRIPTION_FAILED` 的 partial 行为保持不变。
- 最终回复面向人类展示中文状态总结、关键指标、降级项和下一步建议，不强制列出 `runlog.md` / `status.json` 路径，也不粘贴 `status.json` 原文。
- `runlog.md` 如保留，内容中文优先，并定位为内部运行台账；`status.json` 定位为 Agent / 编排器读取的机器契约。
