---
name: document-review
description: |
  Use this skill whenever the user asks to review, proofread, audit, validate, or check a document or pasted text for errors and compliance risks — even if they don't say "审校" or "review" explicitly. Covers 7 problem types: 错别字 / 语病 / 标点 / 格式 / 一致性 / 敏感词 / 合规风险.
  Triggers (zh): 审校/审核/校验/校对/检查/审查/找错/标错, 合同审查/合规检查, 错别字/标点/语病/格式/敏感词/排版, "这份文档/合同/协议/报告有没有问题", "帮我看看这个文档哪里有问题".
  Supports docx, pdf, txt, md, xlsx, xls, xml, and pasted text. Outputs a structured report (校验结论 / 问题清单 / 关键修订稿) and uses map-reduce for long documents so it never bails on large files.
  Do NOT use for: legal/financial/tax conclusions (only risk flags), pure translation, de-AI rewriting, or non-text input (audio/video). For pure OCR, use markitdown.
---

# Document Review Skill

## 1. 使用场景

当用户要求文档校验、文档审核、合同审查、错别字检查、标点检查、格式检查、语法检查、敏感词检查、合规风险检查时，使用本技能。

用户上传文件但未说明检查范围时，默认执行综合审校，不反问。

所有回复使用简体中文。

---
# 文件输入约定
当用户上传文件后，本技能有限使用DeerFlow上传文件的虚拟路径读取文件，再使用markitdown的skill解析文件内容。
---

## 2. 审校范围

按以下 7 种问题类型（与 `validate.py` JSON 输出对齐）检查：

- **typo（错别字）**：错别字、漏字、多字、重复表达
- **grammar（语病）**：句式冗余、语序不顺、表达不清
- **punctuation（标点）**：标点误用、中英文标点混用
- **format（格式）**：日期、金额、数字、单位格式不统一；标题层级、编号、表格结构问题
- **consistency（一致性）**：主体名称、项目名称、金额、日期、编号、术语、引用关系前后不一致
- **sensitive（敏感词）**：敏感词、绝对化表达、广告法风险表达
- **compliance（合规风险）**：合同、协议、采购文件中的条款风险（金额、付款、交付、违约责任等）

## 3. 大文件处理规则

遇到长文档、大文件、多页 PDF、大型 Word、Excel 多表格或内容预计超过单次处理能力时，禁止一次性审查全文。

### 3.1 阈值判断（先做这步）

拿到 markitdown 转换后的 `.md` 后，粗估 token 数：

```bash
# 字节数除以 3 粗估 tokens（中文/英文混排的保守值）
BYTES=$(wc -c < /mnt/user-data/outputs/<stem>.md | tr -d ' ')
TOKENS_EST=$((BYTES / 3))
```

| 估算 tokens | 页数（粗估） | 走哪个流程 |
|---|---|---|
| ≤ 1800 | ≤ 5 页 | **§3.2 单次流程**（小文档，不切分） |
| > 1800 | > 5 页 | **§3.3 map-reduce 流程**（大文档，切分） |

> 阈值 1800 来自 `validate.py` 的 `DEFAULT_CHUNK_SIZE`。

### 3.2 单次流程（小文档，≤ 1800 tokens / ≤ 5 页）

直接把 markdown 内容塞进 LLM 调一次，按第 7 节格式输出报告。

**不要**为了"格式统一"去调 validate.py——小文档 map-reduce 是浪费 token、引入合并误差。

### 3.3 map-reduce 流程（大文档，> 1800 tokens / > 5 页）

1. 调 `python /mnt/skills/public/document-review/scripts/validate.py <输入.md> <输出目录/>` 拿到 map prompts、reduce 模板、chunk 摘要（脚本内部用 markitdown skill 的 chunked_convert 做 token 切分，表格/code block 不切，每块 ≤ chunk_size=1800 tokens）。

2. 对 `result.chunks[]` 每块独立调 LLM（system + user prompt 已在 map_prompt 里），收集所有结果为 JSON 数组。

3. 把 JSON 数组填入 `result.reduce_prompt.user_template` 的两个占位符：
   - `{map_results_json}` ← 第 2 步收集的 JSON 数组
   - `{chunk_summaries}` ← `result["chunk_summaries"]`（每块章节覆盖）
   调 LLM 拿最终 markdown 报告（reduce LLM 的 system prompt 已经要求**直接按第 7 节格式输出 markdown**，不要 JSON）。

4. reduce LLM 的输出**就是**最终报告。Agent 直接把这份 markdown 呈现给用户，**不要再转换**。

5. 不得因为文件过长而直接停止、报错或只给空泛建议。

6. 不要求用户手动拆分文件，除非文件无法读取或内容损坏。

7. **进度展示**（必做，影响用户体验）：map 阶段每调一次 LLM 之前，agent 必须 print 一行进度：
   ```
   🔍 正在审校第 N/M 块...
   ```
   reduce 阶段开始时再 print：
   ```
   📊 正在汇总（reduce 阶段）...
   ```
   全部完成时 print：
   ```
   ✅ 审校完成
   ```
   **不打印的代价**：100 页文档审校 5 分钟内用户看不到任何输出，会以为 agent 卡死。

**输出过长时优先输出**：

1. 校验结论
2. 高风险问题
3. 中风险问题
4. 明显错别字和格式问题
5. 关键修订稿

用户明确要求完整修订稿时，按”第1部分、第2部分、第3部分……”分批输出，直到完成。

**底层工具**：`/mnt/skills/public/markitdown/scripts/chunked_convert.py`（公开工具，本 skill 之外的 skill 也可调用）。

## 4. 文件处理规则

- docx：提取正文、标题、表格、页眉页脚。
- xlsx/xls：按工作表、行列、单元格审查。
- pdf：提取文本；疑似扫描件时提示 OCR 可能存在误差。
- txt/md/xml：保留原结构进行检查。
- 多文件任务逐个处理，并分别给出结论。

文件无法读取、损坏、内容为空或格式不支持时，直接说明原因，不编造审查结果。

## 5. 审校优先级

优先处理：

1. 高风险问题：合同主体、金额、日期、付款、交付、验收、违约责任、解除条款、争议解决、极限词、合规风险。
2. 明显错误：错别字、漏字、多字、语病、标点错误。
3. 格式一致性：标题层级、编号、金额日期格式、术语统一、表格与正文一致性。
4. 表达优化：冗余表达、句式不顺、语气不统一。

合同类文本不得直接判断“合法/违法”，应使用“存在风险、建议明确、建议补充、建议法务确认、可能导致争议”等表述。

## 6. 生产执行规则

- 不随意改写原文含义。
- 不删除金额、日期、主体、权利义务、责任边界等关键信息。
- 不确定内容标注“【需核实】”。
- 合同审查只提供文本风险提示，不构成法律意见。
- 不输出附件、不生成下载文件、不要求用户去附件中查看。
- 不强制输出完整修复全文，避免截断和报错。
- 不因内容过长而拒绝输出有效结果。
- 大文件必须输出可用结果，至少包含问题清单和关键修改建议。

## 7. 默认输出格式

# 一、校验结论

说明整体质量、主要问题、风险等级、优先修改事项。

# 二、问题清单

| 序号 | 位置 | 问题类型 | 原文 | 问题说明 | 风险等级 | 修改建议 |
|---|---|---|---|---|---|---|

风险等级只使用：高 / 中 / 低。

# 三、关键修订稿

只输出重点修改段落或条款。

文档较短时，可输出完整修订稿。

文档较长时，只输出关键修订稿，避免截断和报错。


## 8. 特殊文件输出规则

Excel：

问题清单必须包含工作表名称、行号、列号或列名、原单元格内容、修改建议；不得重打大型完整表格。

XML：

检查标签闭合、层级结构、字段命名、必填字段、错别字和敏感词。

Markdown：

保留标题、列表、表格、代码块和链接格式，不得破坏原结构。

## 9. 禁止行为

- 禁止无依据大幅改写。
- 禁止改变原文事实含义。
- 禁止删除关键条款。
- 禁止伪造事实。
- 禁止输出附件或下载链接。
- 禁止大文件强制输出完整全文。
- 禁止只说“建议自行修改”。
- 禁止因内容长而不输出有效结果。
- 禁止直接作出法律结论。