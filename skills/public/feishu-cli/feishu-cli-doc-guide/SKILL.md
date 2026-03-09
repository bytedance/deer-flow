---
name: feishu-cli-doc-guide
description: 飞书文档创建规范指南。Markdown 语法支持、Mermaid/PlantUML 飞书语法限制、表格处理、图表容错机制等完整规范。供其他飞书技能参考。
user-invocable: false
allowed-tools: Read
---

# 飞书文档创建规范指南

## 1. 概述

本技能是 **其他飞书文档技能的参考规范**，不可直接调用。整合了以下来源的验证经验：

- `feishu-cli` 项目代码实现（`converter/`、`client/board.go`、`cmd/import_markdown.go`）
- `feishu-cli-write`、`feishu-cli-import`、`feishu-cli-plantuml` 技能的实测数据
- 大规模导入测试：10,000+ 行 / 127 个图表 / 170+ 个表格的验证结果

**适用场景**：生成将要导入飞书的 Markdown 文档时，参考本规范确保兼容性。

---

## 2. Markdown 语法全量参考

### 支持的语法与 Block 类型映射

| Markdown 语法 | Block Type | 飞书块名称 | 说明 |
|---------------|-----------|-----------|------|
| `# 标题` ~ `###### 标题` | 3-8 | Heading1-6 | 最多 6 级（7-9 级导出降级为粗体段落） |
| 普通段落 | 2 | Text | 纯文本 |
| `- 无序列表` | 12 | Bullet | 支持无限深度嵌套 |
| `1. 有序列表` | 13 | Ordered | 支持无限深度嵌套 |
| `- [x]` / `- [ ]` | 17 | Todo | 任务列表 |
| `` ```lang `` | 14 | Code | 代码块（支持语言标识） |
| `> 引用` | 34 | QuoteContainer | 引用容器（导入使用 QuoteContainer） |
| `> [!NOTE]` | 19 | Callout | 高亮块（6 种类型，见第 5 节） |
| `---` | 22 | Divider | 分割线 |
| Markdown 表格 | 31 | Table | 超过 9 行或 9 列自动拆分（见第 6 节） |
| `![alt](url)` | 27 | Image | 占位块（见第 7 节） |
| `` ```mermaid `` | 21→43 | Diagram→Board | 自动转飞书画板（见第 3 节） |
| `` ```plantuml `` / `` ```puml `` | 21→43 | Diagram→Board | 自动转飞书画板（见第 4 节） |
| `$$公式$$` | 16 | Equation | 块级公式（降级为行内 Equation） |
| `$公式$` | — | InlineEquation | 行内公式 |

### 新增块类型（导出支持）

以下块类型在导出时有对应的处理：

| Block Type | 名称 | 导出结果 | 说明 |
|------------|------|---------|------|
| 44 | Agenda | 展开子块 | 议程块 |
| 45 | AgendaItem | 展开子块 | 议程条目 |
| 46 | AgendaItemTitle | 粗体文本 | 议程标题 |
| 47 | AgendaItemContent | 展开子块 | 议程内容 |
| 48 | LinkPreview | 链接 | 链接预览块 |
| 49 | SyncSource | 展开子块 | 同步源块 |
| 50 | SyncReference | 展开子块 | 同步引用块 |
| 51 | WikiCatalogV2 | `[知识库目录 V2]` | 知识库目录 V2 |
| 52 | AITemplate | HTML 注释 | AI 模板块 |

### 行内样式

| Markdown | 效果 | 说明 |
|----------|------|------|
| `**粗体**` | **粗体** | Bold TextStyle |
| `*斜体*` | *斜体* | Italic TextStyle |
| `` `行内代码` `` | `代码` | InlineCode TextStyle |
| `~~删除线~~` | ~~删除线~~ | Strikethrough TextStyle |
| `<u>下划线</u>` | 下划线 | Underline TextStyle |
| `[文字](url)` | 链接 | Link TextElement |
| `==高亮==` | 高亮 | Highlight（需启用选项） |

### 嵌套列表示例

```markdown
- 一级无序
  - 二级无序
    - 三级无序
      1. 四级有序
      2. 四级有序
    - 三级无序
  - 二级无序
```

无序/有序列表支持 **无限深度嵌套** 和 **混合嵌套**，导入时自动保留缩进层级。

---

## 3. Mermaid 飞书语法规范

> 这是最重要的章节。Mermaid 图表导入飞书有严格的语法限制，不遵守会导致渲染失败。

### 支持的 8 种图表类型

| 类型 | 声明 | 飞书 diagram_type | 说明 |
|------|------|------------------|------|
| 流程图 | `flowchart TD` / `flowchart LR` | 6 (flowchart) | 支持 subgraph |
| 时序图 | `sequenceDiagram` | 2 (sequence) | 复杂度限制最严格 |
| 类图 | `classDiagram` | 4 (class) | |
| 状态图 | `stateDiagram-v2` | 7 (state) | 必须用 v2 |
| ER 图 | `erDiagram` | 5 (er) | |
| 甘特图 | `gantt` | 0 (auto) | |
| 饼图 | `pie` | 0 (auto) | |
| 思维导图 | `mindmap` | 1 (mindmap) | |

### 6 条强制性规则

#### 规则 1：禁止在标签中使用花括号 `{}`

花括号会被 Mermaid 解析器识别为菱形（decision）节点，导致语法错误。此规则针对 flowchart 节点标签，erDiagram/classDiagram 语法结构中的 `{}` 不受此限制。

```markdown
<!-- ❌ 错误 -->
flowchart TD
    A["{name: value}"]

<!-- ✅ 正确 -->
flowchart TD
    A["name: value"]
```

**替代方案**：移除花括号，或用圆括号/方括号替代。

#### 规则 2：禁止使用 `par...and...end` 并行语法

飞书画板完全不支持 `par` 语法（错误码 2891001）。

```markdown
<!-- ❌ 错误 -->
sequenceDiagram
    par
        A->>B: 请求1
    and
        A->>C: 请求2
    end

<!-- ✅ 正确：用 Note 替代 -->
sequenceDiagram
    Note over A,C: 并行处理
    A->>B: 请求1
    A->>C: 请求2
```

#### 规则 3：方括号中避免冒号

方括号 `[text:xxx]` 中的冒号可能导致解析歧义。

```markdown
<!-- ❌ 可能出错 -->
flowchart TD
    A[类型:string]

<!-- ✅ 正确 -->
flowchart TD
    A["类型: string"]
```

**修复方法**：给含冒号的标签加双引号。

#### 规则 4：Note 作用域限制

`Note over` 最多跨 2 个相邻 participant。

```markdown
<!-- ❌ 错误：跨太多参与者 -->
sequenceDiagram
    Note over A,D: 说明

<!-- ✅ 正确 -->
sequenceDiagram
    Note over A,B: 说明
```

#### 规则 5：sequenceDiagram 复杂度阈值

| 维度 | 安全阈值 | 超限风险 |
|------|---------|---------|
| participant 数量 | ≤ 8 | 超过 10 + 其他因素 → 失败 |
| alt/opt 嵌套 | ≤ 1 层 | 超过 2 层 → 失败风险增大 |
| 消息标签长度 | 简短（≤ 30 字符） | 长标签 + 多参与者 → 失败 |
| 总消息数 | ≤ 30 | 需结合其他因素评估 |

**超限组合**（实测必定失败）：10+ participant + 2+ alt + 30+ 长消息标签

**建议**：超过安全阈值时，拆分为多个小图。

#### 规则 6：避免过于复杂的嵌套结构

多层 subgraph 嵌套、大量条件分支等复杂结构会增加渲染失败概率。保持图表简洁。

### 生成前检查清单

在生成 Mermaid 代码块前，逐项检查：

- [ ] 图表类型是否在支持的 8 种之内？
- [ ] 标签中是否存在花括号 `{}`？→ 移除或替换
- [ ] 是否使用了 `par...and...end`？→ 改用 `Note over`
- [ ] 方括号标签中是否有冒号？→ 加双引号
- [ ] sequenceDiagram 参与者是否 ≤ 8？
- [ ] sequenceDiagram alt 嵌套是否 ≤ 1 层？
- [ ] 整体复杂度是否可控？→ 考虑拆分

> 详细的 8 种图表模板和更多正反示例见 `references/mermaid-spec.md`。

---

## 4. PlantUML 安全子集

### 全局规则

1. 使用 `@startuml` / `@enduml` 包裹（思维导图用 `@startmindmap` / `@endmindmap`）
2. **不要使用行首缩进**（飞书画板将缩进行视为独立行）
3. 避免 `skinparam`、`!define`、颜色、字体、对齐控制等样式指令
4. 避免方向控制指令（`left to right direction` 等在部分场景不可靠）

### 各图类型注意事项

| 图类型 | 安全语法 | 禁忌 |
|--------|---------|------|
| 活动图 | `start/stop`、`:动作;`、`if/then/else/endif`、`repeat`、`fork` | 避免过深嵌套 |
| 时序图 | `participant`、`->`/`-->`、`activate/deactivate`、`note`、`alt/opt/loop` | 避免样式指令 |
| 类图 | `class`、`interface`、`package`、关系箭头 | **避免可见性标记（+ - # ~）** |
| 用例图 | `actor`、`(用例)`、`<<include>>`/`<<extend>>` | 避免复杂布局 |
| 组件图 | `[Component]`、`package/node/cloud/database` | 避免 ArchiMate sprite |
| ER 图 | `entity`、关系箭头 | 与 Mermaid ER 语法不同 |
| 思维导图 | `@startmindmap`、`* / +` 层级标记 | 必须用专用包裹标记 |

### Mermaid vs PlantUML 选择策略

| 场景 | 推荐 | 原因 |
|------|------|------|
| 流程图 | **Mermaid** | 飞书原生支持更好，成功率高 |
| 时序图（简单） | **Mermaid** | 语法简洁 |
| 时序图（复杂） | PlantUML | Mermaid 复杂度限制严格 |
| 类图 | Mermaid | 两者都可，Mermaid 更简洁 |
| ER 图 | Mermaid | 语法更直观 |
| 状态图 | Mermaid | stateDiagram-v2 支持好 |
| 甘特图 | **Mermaid** | PlantUML 甘特图飞书支持差 |
| 饼图 | **Mermaid** | 简洁 |
| 思维导图 | 两者均可 | PlantUML 层级标记更灵活 |
| 用例图 | **PlantUML** | Mermaid 不支持 |
| 组件图 | **PlantUML** | Mermaid 不支持 |
| 活动图（复杂分支） | **PlantUML** | 支持更丰富的分支语法 |

**默认推荐 Mermaid**，仅在 Mermaid 不支持的图类型或复杂场景下使用 PlantUML。

---

## 5. Callout 高亮块

### 6 种类型与背景色映射

| 类型 | bgColor | 颜色 | Markdown 语法 | 适用场景 |
|------|---------|------|--------------|---------|
| NOTE / INFO | 6 | 蓝色 | `> [!NOTE]` | 补充说明、提示信息 |
| WARNING | 2 | 红色 | `> [!WARNING]` | 警告、危险提醒 |
| TIP | 4 | 黄色 | `> [!TIP]` | 技巧、建议 |
| CAUTION | 3 | 橙色 | `> [!CAUTION]` | 注意事项 |
| IMPORTANT | 7 | 紫色 | `> [!IMPORTANT]` | 重要信息 |
| SUCCESS | 5 | 绿色 | `> [!SUCCESS]` | 成功、通过 |

### 使用示例

```markdown
> [!NOTE]
> 这是一条补充说明信息。

> [!WARNING]
> 此操作不可逆，请谨慎执行。

> [!TIP]
> 使用 `--verbose` 参数可以查看详细进度。

> [!CAUTION]
> 注意：API 有频率限制。

> [!IMPORTANT]
> 必须在执行前配置环境变量。

> [!SUCCESS]
> 所有测试用例已通过。
```

### 注意事项

- Callout 块不能同时设置 `EmojiId`，仅通过 `BackgroundColor` 区分类型
- 支持 Callout 内包含子块（段落、列表等）
- `INFO` 和 `NOTE` 等效，都映射为蓝色 (bgColor=6)

---

## 6. 表格规范

### 9 行 × 9 列限制与自动拆分

飞书 API 限制单个表格最多 **9 行**（包括表头）× **9 列**。超出时 feishu-cli 自动拆分为多个表格。

拆分逻辑（`converter/markdown_to_block.go`）：

| 维度 | 处理方式 |
|------|---------|
| ≤ 9 行 且 ≤ 9 列 | 直接创建单个表格 |
| > 9 行 | 按行拆分为多个表格，每个最多 8 行数据 + 1 行表头 |
| > 9 列 | 按列拆分为多个表格，保留首列作为标识列 |
| > 9 行 且 > 9 列 | 先列拆分，再行拆分（复合拆分） |

**列拆分策略**：首列通常是标识/名称列，在所有列组中保留，避免拆分后数据行无法识别。每个列组最多 9 列（1 列标识 + 8 列数据）。

### 列宽自动计算

列宽根据单元格内容自动计算（`converter/markdown_to_block.go:25-103`）：

| 参数 | 值 | 说明 |
|------|-----|------|
| 中文字符宽度 | 14px | 非 ASCII 字符 |
| 英文字符宽度 | 8px | ASCII 字符 |
| 列内边距 | 16px | 每列额外边距 |
| 最小列宽 | 80px | 不能更窄 |
| 最大列宽 | 400px | 不能更宽 |
| 文档默认宽度 | 700px | 总宽度不足时按比例扩展 |

### 单元格多块支持

表格单元格内可以包含多种块类型：

- Text（普通文本）
- Bullet（无序列表）
- Heading（标题）

**注意**：飞书 API 创建表格时会自动在每个单元格内创建空的 Text 块。填充内容时应 **更新现有块** 而非创建新块。

### 表格编写建议

```markdown
| 列1 | 列2 | 列3 |
|-----|-----|-----|
| 数据 | 数据 | 数据 |
```

- 确保每行列数一致
- 大表格（超过 8 行数据或超过 9 列）会自动拆分，无需手动处理
- 列宽由内容自动决定，无需手动控制

---

## 7. 图片处理

### 当前限制

飞书 DocX Open API **不支持通过 API 插入实际图片内容**。`feishu-cli` 的处理方式：

1. 遇到 `![alt](url)` 时，创建一个空的 **Image 占位块**（BlockType=27）
2. 导入完成后，报告中显示 **跳过的图片数量**
3. 用户需要在飞书文档中手动替换图片

### 建议

- 如果文档中有大量图片，考虑在导入后手动上传
- 可以使用 `feishu-cli media upload` 上传素材到飞书，获取文件 token
- 图片相关的 alt 文字会作为占位信息保留

---

## 8. 公式

### 行内公式

使用单美元符号包裹：`$E = mc^2$`

支持一个段落内包含多个行内公式：

```markdown
已知 $a^2 + b^2 = c^2$，当 $a = 3, b = 4$ 时，$c = 5$。
```

### 块级公式

使用双美元符号包裹：

```markdown
$$
\int_{-\infty}^{\infty} e^{-x^2} dx = \sqrt{\pi}
$$
```

### 注意事项

- 飞书 API 不支持直接创建块级 Equation（BlockType=16），实际导入时 **降级为行内 Equation**
- LaTeX 语法兼容飞书 KaTeX 渲染器
- 公式中的特殊字符无需额外转义

---

## 9. API 限制与容错

### 三阶段并发管道

`feishu-cli doc import` 采用三阶段管道架构（`cmd/import_markdown.go`）：

| 阶段 | 方式 | 处理内容 |
|------|------|---------|
| 阶段一 | **顺序** | 按文档顺序创建所有块，为图表创建空画板占位块，收集表格任务 |
| 阶段二 | **并发** | 图表 worker 池（默认 5 并发）+ 表格 worker 池（默认 3 并发）同时处理 |
| 阶段三 | **逆序** | 处理失败的图表：删除空画板块，在原位置插入代码块（逆序避免索引偏移） |

### 批量操作限制

| 限制 | 值 | 处理方式 |
|------|-----|---------|
| 单次创建块数 | 最多 50 个 | 自动分批（`batchSize = 50`） |
| 单个表格行数 | 最多 9 行 | 自动拆分并复制表头 |
| 单个表格列数 | 最多 9 列 | 自动拆分并保留首列 |
| 文件夹子节点 | 不超过 1500 | 超出报错 1062507 |
| 文档块总数 | 有上限 | 超出报错 1770004 |
| 文件大小 | 最大 100MB | 超出直接报错 |
| API 频率 | 429 Too Many Requests | 自动重试 + 线性退避 |

### 图表重试与降级策略

| 错误类型 | 判断条件 | 处理方式 |
|---------|---------|---------|
| 语法错误 | `Parse error`、`Invalid request parameter` | **不重试**，直接降级为代码块 |
| 服务端错误 | 500/502/503、`internal error` | 重试（最多 10 次，1s 间隔） |
| 频率限制 | 429、`rate limit`、`frequency limit` | 重试（归为可重试错误） |
| 重试耗尽 | 超过最大重试次数 | 降级为代码块 |

降级处理流程：
1. 获取文档所有顶层子块
2. 按索引 **逆序** 处理失败图表（避免删除导致索引偏移）
3. 删除空画板块
4. 在原位置插入代码块（保留原始图表代码）

### CLI 并发控制参数

| 参数 | 默认值 | 说明 |
|------|-------|------|
| `--diagram-workers` | 5 | 图表（Mermaid/PlantUML）并发导入数 |
| `--table-workers` | 3 | 表格并发填充数 |
| `--diagram-retries` | 10 | 图表最大重试次数 |
| `--verbose` | false | 显示详细进度 |

### 画板 API 技术细节

- API 端点：`/open-apis/board/v1/whiteboards/{id}/nodes/plantuml`
- `syntax_type`：1 = PlantUML，2 = Mermaid
- `diagram_type` 映射：0=auto, 1=mindmap, 2=sequence, 3=activity, 4=class, 5=er, 6=flowchart, 7=state, 8=component

---

## 10. 最佳实践检查清单

创建将导入飞书的 Markdown 文档前，完成以下检查：

### 文档结构

- [ ] 标题层级不超过 6 级（H7-H9 会降级为粗体段落）
- [ ] 嵌套列表使用 2 或 4 空格缩进
- [ ] 表格数据行控制在 8 行以内（避免不必要拆分）
- [ ] 文件总大小不超过 100MB

### Mermaid 图表

- [ ] 图表类型在支持的 8 种之内
- [ ] 标签无花括号 `{}`
- [ ] 未使用 `par...and...end`
- [ ] 方括号标签内含冒号时已加双引号
- [ ] sequenceDiagram：participant ≤ 8，alt ≤ 1 层
- [ ] 复杂图表已拆分为多个小图

### PlantUML 图表

- [ ] 使用正确的包裹标记（`@startuml`/`@enduml`）
- [ ] 无行首缩进
- [ ] 无 `skinparam` 等样式指令
- [ ] 类图未使用可见性标记（`+ - # ~`）

### 特殊内容

- [ ] 图片已标注（导入后需手动替换）
- [ ] 公式语法正确（`$...$` 行内 / `$$...$$` 块级）
- [ ] Callout 类型在 6 种之内（NOTE/WARNING/TIP/CAUTION/IMPORTANT/SUCCESS）

### 性能考虑

- [ ] 大量图表时考虑增加 `--diagram-workers`
- [ ] 大量表格时考虑增加 `--table-workers`
- [ ] 首次导入建议加 `--verbose` 观察进度
