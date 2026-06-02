## Context

已有基础设施：
- `PassthroughParamsMiddleware` 已将 deep-link 参数注入消息内容的 `<deep_link_params>` 块
- 故障诊断 Agent 已证明 "跳过表单直达执行" 模式有效
- 日报 Agent 有 auto_start starter ("生成日报")，但 deep-link 指令只做预填不跳过表单
- 周报/月报 Agent 有 auto_start starter，但完全没有 deep-link 参数指令

## Goals / Non-Goals

**Goals:**
- 日报：`template_id` + `date` 齐全 → 跳过全部表单，直接执行 DSL 报告生成到完成
- 周报：`template_id` + `date_start` + `date_end` 齐全 → 跳过表单，直达报告
- 月报：`template_id` + `month` 齐全 → 跳过表单，直达报告
- 参数缺失或校验失败时回退到正常表单流程

**Non-Goals:**
- 不修改前端/后端代码
- 不新增 API 端点
- 不改变报告生成逻辑本身

## Decisions

### 参数设计

| Agent | 参数 | 说明 |
|-------|------|------|
| 日报 | `template_id` + `date` | 沿用现有参数，改行为从 "预填" → "直达" |
| 周报 | `template_id` + `date_start` + `date_end` | 与周报表单字段对齐（`date_start`/`date_end`） |
| 月报 | `template_id` + `month` | 与月报表单字段对齐（`month` 格式 `YYYY-MM`） |

### 指令写法

参照故障诊断已验证的表述："跳过 GenUI 表单流程，直接进入执行步骤"。关键差异：
- 报告 Agent 走 DSL 路径（`prepare_run` → `form_steps` → `data_pipeline` → `render` → `export`）
- deep-link 参数直接填入各步骤，不需要 `render_ui` 创建交互表单

### API 文档

在 `docs/deep-link-api.md` 中新增第 7.1 节（周报）和第 7.2 节（月报），紧接在日报（第 7 节）之后。

## Risks / Trade-offs

- **[Risk] LLM 可能不完全按指令跳过表单** → **Mitigation**: 指令使用与故障诊断一致的明确措辞，并列出具体的跳过步骤清单
- **[Risk] 模板不存在时行为未定义** → **Mitigation**: 指令中明确：`template_id` 不存在时回退到模板选择表单
