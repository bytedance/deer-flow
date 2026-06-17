# DeerFlow Q&A 内容跟踪 — 功能设计

- **Date**: 2026-06-17
- **对应 spec**: `2026-06-17-deerflow-qa-tracking-design.md`
- **对应设计问题**: `2026-06-17-deerflow-qa-tracking-design-questions.md`
- **本文档作用**：定义"功能是什么"——用户视角的行为、入口、流程、过滤、导出、权限
- **不包含**：技术架构、API 详细 schema、数据流（→ 第三个文档）

---

## 1. 用户画像

| 画像 | 角色 | 可见性 |
|------|------|--------|
| **管理员（admin）** | DeerFlow 部署方、产品负责人、运维、QA | ✅ 看到所有用户的 Q&A |
| **普通用户（user）** | DeerFlow 的终端用户 | ❌ 看不到分析页（仍可在原 workspace 看自己的 thread） |

**为什么只有 admin**：DeerFlow 是 self-hosted 工具，admin 角色负责"系统级观察"，普通用户关心"自己的对话"。两个视角分开，避免 admin 端误暴露普通用户内容。

**auth_disabled 模式**：默认放行（与现有 admin endpoint 一致），适用于纯本地无人登录场景。

---

## 2. 入口

### 2.1 入口位置

**菜单**：左侧导航栏底部，仅 `is_admin === true` 时显示 "Q&A Analytics" 链接。

**直接 URL**：`/admin/analytics`

**未授权访问**：跳转到 `/`（workspace 页），或显示 "Admin only" 提示。

### 2.2 与现有入口的关系

- 与"Settings"并列在左侧导航
- 不与现有 thread / workspace 页面混杂
- admin 用户可以同时打开 thread 页和 analytics 页（不同 tab 互不影响）

---

## 3. 页面布局

### 3.1 整体结构

```
┌──────────────────────────────────────────────────────────────┐
│  [DeerFlow Logo]  Workspace   Threads   Models   Settings  Q&A Analytics │
├──────────────────────────────────────────────────────────────┤
│                                                                │
│  Q&A Analytics                                                │
│  ┌──────────────────────────────────────────────────────────┐│
│  │ Filters                                                   ││
│  │ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───┐││
│  │ │Date range│ │User      │ │Assistant │ │Model     │ │Sta│││
│  │ └──────────┘ └──────────┘ └──────────┘ └──────────┘ └───┘││
│  │ Search: [____________________________________________]    ││
│  │                                            [Apply][Reset]││
│  └──────────────────────────────────────────────────────────┘│
│                                                                │
│  Showing 1-50 of 1,234 runs         [Export CSV] [Export JSONL]│
│  ┌──────────────────────────────────────────────────────────┐│
│  │ Time       │ User  │ Asst    │ Model │ Tokens │ Status │►│
│  │ 2026-06-17 │ alice │ lead-ag │ gpt-4 │ 12.3k  │success │ ││
│  │ "How do I..."                                              ││
│  │ ...                                                        ││
│  └──────────────────────────────────────────────────────────┘│
│                                                                │
│                              [< Prev] Page 1 of 25 [Next >]   │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 各区域行为

**Filters 区域**：
- Date range：两个日期输入框（from、to），含日历选择器；可单独使用一方
- User：下拉多选，显示所有出现过的 user_id（从 list 接口的 `available_filters` 字段取）
- Assistant：下拉单选
- Model：下拉单选
- Status：下拉单选（pending/running/success/error/timeout/interrupted）
- Search：文本输入，对首轮用户提问 + AI 最终回答做模糊匹配
- Apply 按钮：触发新查询
- Reset 按钮：清空所有 filter，回到默认（仅 date range 默认最近 7 天）

**Table 区域**：
- 默认按时间倒序
- 列：Time / User / Assistant / Model / Tokens / Status
- 每行下方有 preview（首轮 HumanMessage 前 80 字符）
- 行点击 → 右侧 drawer 显示完整内容（见 §4）
- Hover：背景色变化
- Loading：骨架屏

**Pagination**：
- 默认 page_size = 50
- 每页底部显示 "Showing X-Y of Z"
- Prev / Next 按钮 + 直接跳转到 N 页

**Export 区域**：
- Export CSV 按钮：按当前 filter 导出全部匹配行（不分页）
- Export JSONL 按钮：同上
- 按钮触发浏览器下载，文件名 `deerflow-runs-{timestamp}.csv` 或 `.jsonl`

---

## 4. 详情视图（Drawer）

### 4.1 触发

- 点击 Table 中任意一行 → 右侧滑出 drawer
- Drawer 宽度固定 480px
- 点击 drawer 外或 X 按钮 → 关闭

### 4.2 Drawer 内容

```
┌────────────────────────────────────────┐
│ Run Detail                            [X]│
├────────────────────────────────────────┤
│ Run ID    abc123...                   │
│ Thread ID def456...                   │
│ User      alice                       │
│ Assistant lead-agent                  │
│ Model     gpt-4o                      │
│ Status    success                     │
│ Started   2026-06-17 10:23:45         │
│ Ended     2026-06-17 10:24:01         │
│ Duration  16s                         │
├────────────────────────────────────────┤
│ User Question                          │
│ ┌────────────────────────────────────┐ │
│ │ [完整 first_human_message 文本]     │ │
│ │ How do I configure the agent to     │ │
│ │ use a custom model?                 │ │
│ └────────────────────────────────────┘ │
├────────────────────────────────────────┤
│ AI Answer                              │
│ ┌────────────────────────────────────┐ │
│ │ [完整 last_ai_message 文本]          │ │
│ │ To configure a custom model, you    │ │
│ │ need to add a new entry in your     │ │
│ │ config.yaml under `models[]`...     │ │
│ └────────────────────────────────────┘ │
├────────────────────────────────────────┤
│ Resources                              │
│ Total tokens:     1,801                │
│   - Input:        1,234                │
│   - Output:         567                │
│   - Lead agent:   1,500                │
│   - Subagent:       200                │
│   - Middleware:     100                │
│ LLM calls:        3                    │
├────────────────────────────────────────┤
│ Error (only if status != success)      │
│ ┌────────────────────────────────────┐ │
│ │ [完整 error 文本]                    │ │
│ └────────────────────────────────────┘ │
├────────────────────────────────────────┤
│ Follow-up Run:                         │
│   ▶ run_id=xyz789 (click to navigate) │
└────────────────────────────────────────┘
```

**长文本处理**：
- 单个消息 > 5000 字符：drawer 内显示区域带"show more" 折叠
- 默认折叠后展示前 500 字符，点击展开

**关联**：
- Thread ID 可点击 → 跳转到该 thread 的原 workspace 页
- Follow-up Run ID 可点击 → 抽屉切到该 run 的详情

---

## 5. 过滤器行为

### 5.1 过滤器之间的逻辑

所有 filter 之间是 **AND** 关系：
- `q=foo` + `status=success` = "首轮或最终回答含 foo" AND "状态是 success"

User 是 **OR** 关系（如果选多个 user_id）：
- `user_id=alice` + `user_id=bob` = "alice 或 bob 的 run"

### 5.2 过滤器的持久化

- Filter 状态通过 URL query string 持久化（`?date_from=...&user_id=...&q=...`）
- 复制 URL 给他人可复现相同 filter
- 浏览器后退/前进按钮正常工作

### 5.3 默认行为

- 首次进入：`date_from = (now - 7 days)`、`date_to = now`、其他空
- 避免"全量无 filter"导致加载过久

### 5.4 Search 行为

- 对 `first_human_message` 和 `last_ai_message` 同时匹配
- 大小写不敏感
- 支持中英文（无特殊分词）
- 输入即生效（debounce 300ms），不需点 Apply

---

## 6. 导出行为

### 6.1 触发

- 点击 Export CSV / Export JSONL 按钮 → 触发浏览器下载
- 导出遵循当前所有 filter（与 Table 显示一致）
- 不分页：导出所有匹配行

### 6.2 文件格式

**CSV**：
- 第一行是 header：`run_id,thread_id,user_id,assistant_id,model_name,status,message_count,total_input_tokens,total_output_tokens,total_tokens,llm_call_count,created_at,updated_at,first_human_message,last_ai_message,error`
- 每个字段按 CSV 标准转义（含逗号/引号/换行的字段用双引号包裹，内部引号转义为 `""`）
- 编码 UTF-8 with BOM（确保 Excel 中文不乱码）

**JSONL**：
- 每行一个 JSON 对象
- 字段 schema 与 detail 视图一致
- 不需要顶层 array / 元数据
- 每行以 `\n` 分隔

### 6.3 文件命名

`deerflow-runs-YYYYMMDD-HHMMSS.csv` 或 `.jsonl`

### 6.4 大文件下载

- 流式输出，浏览器边下边显示进度
- 超过 100 MB 时前端提示"文件较大，请耐心等待"
- 服务器端限制：单次导出最多 100,000 行（超过返回 400 提示缩小 filter）

---

## 7. 空状态与错误状态

### 7.1 空结果

```
┌──────────────────────────────────────────┐
│           No runs match your filters     │
│                                          │
│  Try removing some filters or            │
│  adjusting the date range.               │
│                                          │
│  [Clear All Filters]                     │
└──────────────────────────────────────────┘
```

### 7.2 Loading 状态

- Table 加载中：显示 5 行骨架屏
- Filter 加载中：filter 控件 disabled
- Drawer 加载中：显示 spinner

### 7.3 错误状态

- API 错误 → Toast "Failed to load runs, please try again"
- 网络断开 → Toast "Network error, check connection"
- 权限变更（中途被撤销）→ 跳转到登录页或显示 "Permission denied"
- Export 失败 → Toast "Export failed, please try again"，按钮重新可点

---

## 8. 性能预期

| 操作 | 数据规模 | 预期响应 |
|------|---------|---------|
| List 1 页（50 行） | 10k runs 总数 | < 500ms |
| Detail | 单 run | < 100ms |
| Export 1000 行 CSV | - | < 2s |
| Export 10000 行 CSV | - | < 10s |
| 加载空 Filter 下拉 | - | < 300ms |

**超过预期时**：Table 内显示"loading takes longer than expected, click to retry"。

---

## 9. 无障碍 / 国际化

- 所有控件有 aria-label
- 键盘导航：Tab 可达所有 filter、按钮、行
- Enter 触发 Apply / 打开 drawer
- 语言：与现有 UI 一致（i18n 资源待后续扩展，本 spec 内字符串硬编码中文/英文都可）

---

## 10. 与现有 UI 的对比

| 维度 | 现有 thread 页 | 新 analytics 页 |
|------|---------------|----------------|
| 视角 | 单 thread | 全量 run |
| 用户 | 任何用户 | admin only |
| 内容 | 完整多轮对话 | 简化（首轮 + 最终） |
| 过滤 | thread 内搜索 | 跨 thread 全维度 |
| 导出 | 无 | CSV / JSONL |
| 性能 | 流式（前端友好） | 数据库查询（适合大列表） |

两者**互不替代**：thread 页是"我做这个项目时的对话"，analytics 是"我看所有用户做了什么"。

---

## 11. 一句话功能总结

**功能上**：admin 用户能在 `/admin/analytics` 页浏览、筛选、详情查看、CSV/JSONL 导出 DeerFlow 所有历史 run 的"用户提问 + AI 回答"。

**不做**：实时推送、用户自查面板、完整对话回放、聚合 dashboard、quality metrics、Nginx 日志接入、NPS。

**前提**：`RunRow.first_human_message` 和 `last_ai_message` 字段在每次 run 完成时被正确填充（Task 0 验证）。