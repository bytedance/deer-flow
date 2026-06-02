## 1. 日报 — 修改 deep-link 行为从预填到直达

- [x] 1.1 重写 `agents/builtin/ai-report--daily/SOUL.md` 的 `### Deep-Link 参数` 章节：参数齐全时跳过全部表单，直接执行 DSL 完整链路
- [x] 1.2 在指令中明确：`template_id` 不存在时回退到模板选择表单，`date` 缺失时回退到日期表单

## 2. 周报 — 新增 deep-link 直达

- [x] 2.1 在 `agents/builtin/ai-report--weekly/SOUL.md` 新增 `## Deep-Link 参数直达` 章节（放在 `## 核心原则` 之后）
- [x] 2.2 定义参数：`template_id`（模板 ID）、`date_start`（开始日期 `YYYY-MM-DD`）、`date_end`（结束日期 `YYYY-MM-DD`）
- [x] 2.3 指令：三参数齐全且校验通过时，跳过 Round 1/2 表单，直接填参执行报告生成

## 3. 月报 — 新增 deep-link 直达

- [x] 3.1 在 `agents/builtin/ai-report--monthly/SOUL.md` 新增 `## Deep-Link 参数直达` 章节（放在 `## 核心原则` 之后）
- [x] 3.2 定义参数：`template_id`（模板 ID）、`month`（月份 `YYYY-MM`）
- [x] 3.3 指令：两参数齐全且校验通过时，跳过 Round 1/2 表单，直接填参执行报告生成

## 4. API 文档

- [x] 4.1 在 `docs/deep-link-api.md` 新增第 7.1 节"周报"、第 7.2 节"月报"（紧跟日报之后）
- [x] 4.2 每个接口包含：URL、参数表、请求示例、调用方验证方式
