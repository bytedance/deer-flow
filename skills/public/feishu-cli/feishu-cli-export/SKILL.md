---
name: feishu-cli-export
description: >-
  将飞书文档或知识库文档导出为 Markdown 文件，或导出为 PDF/Word/Excel 等格式（异步任务）。
  也支持从本地 DOCX/XLSX 文件导入为飞书云文档。当用户请求"导出文档"、"转换为 Markdown"、
  "保存为 md"、"导出 PDF"、"导出 Word"、"docx 转飞书"、"导入 docx"时使用。
  Markdown 作为中间格式存储在 /tmp 目录。
argument-hint: <document_id|node_token|url> [output_path]
user-invocable: true
allowed-tools: Bash, Read
---

# 飞书文档导出技能

将飞书云文档或知识库文档导出为本地 Markdown 文件，或导出为 PDF/Word 等格式。

## 核心概念

**Markdown 作为中间态**：本地文档与飞书云文档之间通过 Markdown 格式进行转换，中间文件默认存储在 `/tmp` 目录中。

## 使用方法

```bash
# 导出普通文档
/feishu-export <document_id>
/feishu-export <document_id> ./output.md

# 导出知识库文档
/feishu-export <wiki_url>
```

## 执行流程

1. **解析参数**
   - 判断 URL 类型：
     - `/docx/` → 普通文档
     - `/wiki/` → 知识库文档
   - document_id：必需
   - output_path：可选，默认 `/tmp/<id>.md`

2. **执行导出**

   **普通文档**:
   ```bash
   feishu-cli doc export <document_id> --output <output_path>
   ```

   **知识库文档**:
   ```bash
   feishu-cli wiki export <node_token> --output <output_path>
   ```

3. **验证结果**
   - 读取导出的 Markdown 文件
   - 显示文件大小和内容预览

## 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| document_id/node_token | 文档 ID 或知识库节点 Token | 必需 |
| output_path | 输出文件路径 | `/tmp/<id>.md` |
| --download-images | 下载文档中的图片和画板（画板自动导出为 PNG） | 否 |
| --assets-dir | 图片和画板的保存目录 | `./assets` |
| --front-matter | 添加 YAML front matter（标题和文档 ID） | 否 |
| --highlight | 保留文本颜色和背景色（输出为 HTML `<span>` 标签） | 否 |
| --expand-mentions | 展开 @用户为友好格式（需要 contact:user.base:readonly 权限） | 是（默认开启） |

## 支持的 URL 格式

| URL 格式 | 类型 | 命令 |
|---------|------|------|
| `https://xxx.feishu.cn/docx/<id>` | 普通文档 | `doc export` |
| `https://xxx.feishu.cn/wiki/<token>` | 知识库 | `wiki export` |
| `https://xxx.larkoffice.com/docx/<id>` | 普通文档 | `doc export` |
| `https://xxx.larkoffice.com/wiki/<token>` | 知识库 | `wiki export` |

## 输出格式

```
已导出文档！
  文件路径: /path/to/output.md
  文件大小: 2.5 KB

内容预览:
---
# 文档标题
...
```

## 示例

```bash
# 导出普通文档
/feishu-export <document_id>
/feishu-export <document_id> ~/Documents/doc.md

# 导出知识库文档
/feishu-export https://xxx.feishu.cn/wiki/<node_token>
/feishu-export <node_token> ./wiki_doc.md

# 导出并下载图片
/feishu-export <document_id> --download-images

# 导出并添加 YAML front matter
/feishu-export <document_id> -o doc.md --front-matter

# 导出并保留文本高亮颜色
/feishu-export <document_id> -o doc.md --highlight
```

### Front Matter 输出格式

使用 `--front-matter` 时，导出的 Markdown 文件顶部会添加：

```yaml
---
title: "文档标题"
document_id: ABC123def456
---
```

### 高亮颜色输出格式

使用 `--highlight` 时，带颜色的文本会输出为 HTML `<span>` 标签：

```html
<span style="color: #ef4444">红色文本</span>
<span style="background-color: #eff6ff">蓝色高亮背景</span>
```

支持的颜色：7 种字体颜色（红/橙/黄/绿/蓝/紫/灰）+ 14 种背景色（浅/深各 7 种）。

## 图片处理（重要）

导出文档时务必下载图片，以便后续理解图片内容：

### 导出并下载图片

```bash
# 普通文档
feishu-cli doc export <document_id> \
  --output /tmp/doc.md \
  --download-images \
  --assets-dir /tmp/doc_assets

# 知识库文档
feishu-cli wiki export <node_token> \
  --output /tmp/wiki.md \
  --download-images \
  --assets-dir /tmp/wiki_assets
```

### 查看和理解图片

```bash
# 查看下载的图片列表
ls -la /tmp/doc_assets/

# 使用 Read 工具读取图片（Claude 支持多模态）
# Read /tmp/doc_assets/image_1.png
# Read /tmp/doc_assets/image_2.png
```

### 完整流程

1. **导出时添加图片参数**：`--download-images --assets-dir <dir>`
2. **检查图片文件**：`ls <assets_dir>/`
3. **读取图片内容**：使用 Read 工具逐个读取图片
4. **整合分析**：将图片描述与文档文本结合

## 错误处理与边界情况

### 1. 常见错误

| 错误 | 原因 | 解决 |
|------|------|------|
| `code=131002, param err` | 参数错误 | 检查 token 格式 |
| `code=131001, node not found` | 节点不存在 | 检查 token 是否正确 |
| `code=131003, no permission` | 无权限访问 | 确认应用有 docx:document 或 wiki:wiki:readonly 权限 |
| `code=99991672, open api request rate limit` | API 限流 | 等待几秒后重试 |
| `write /tmp/xxx.md: permission denied` | 文件权限问题 | 检查输出目录权限，更换输出路径 |

### 2. 边界情况处理

**情况 1：目录节点导出**
- 知识库目录节点导出内容可能显示为 `[Wiki 目录...]`
- 这是正常行为，表示该节点是目录而非实际文档
- 使用 `wiki nodes <space_id> --parent <token>` 获取子节点

**情况 2：文档内容为空**
- 检查文档是否真的为空
- 检查是否有权限查看内容
- 检查是否是目录节点

**情况 3：图片下载失败**
- 检查 `--assets-dir` 目录是否存在且可写
- 检查网络连接
- 图片可能已被删除或权限不足

**情况 4：导出中断**
- 大型文档导出可能耗时较长
- 如果中断，可以重新执行命令
- 使用 `--output` 指定固定路径以便续传

### 3. 重试机制

如果遇到网络错误或 API 限流：

```bash
# 添加 --debug 查看详细错误信息
feishu-cli doc export <doc_id> --debug

# 等待几秒后重试
sleep 5 && feishu-cli doc export <doc_id>
```

## 已知问题

| 问题 | 说明 |
|------|------|
| 表格导出 | 表格内单元格内容可能显示为 `<!-- Unknown block type: 32 -->`，这是块类型 32（表格单元格）的已知转换问题 |
| 目录节点 | 知识库目录节点导出内容为 `[Wiki 目录...]`，需单独获取子节点 |

## 导出块类型支持

| 飞书块类型 | 导出结果 | 说明 |
|-----------|---------|------|
| 标题 (Heading 1-6) | `# ~ ######` | |
| 标题 (Heading 7-9) | `######` 或粗体段落 | 超出 H6 时降级 |
| 段落 (Text) | 普通文本 | |
| 无序列表 (Bullet) | `- item` | 支持无限深度嵌套 |
| 有序列表 (Ordered) | `1. item` | 保留原始编号序列 |
| 任务列表 (Todo) | `- [x]` / `- [ ]` | |
| 代码块 (Code) | ` ```lang ``` ` | 使用原始文本，无转义 |
| 引用 (Quote) | `> text` | |
| 引用容器 (QuoteContainer) | `> text` | 支持嵌套引用 |
| **Callout 高亮块** | `> [!TYPE]` | 6 种类型 |
| **公式 (Equation)** | `$formula$` | 块级公式 |
| **行内公式** | `$formula$` | 段落内嵌公式 |
| 分割线 (Divider) | `---` | |
| 表格 (Table) | Markdown 表格 | 管道符自动转义 |
| 图片 (Image) | `\[Image: url\]` | |
| 链接 | `[text](url)` | URL 特殊字符自动编码 |
| 画板 (Board) | `[画板/Whiteboard](feishu://board/...)` 或 PNG 图片 | 使用 `--download-images` 时自动导出为 PNG |
| **ISV 块** | 画板链接或 HTML 注释 | Mermaid 绘图/时间线 |
| **Iframe** | `<iframe>` HTML 标签 | 嵌入内容 |
| **AddOns/SyncedBlock** | 展开子块内容 | 透明展开 |
| Wiki 目录 | `[Wiki 目录...]` | |
| **Agenda/AgendaItem** | 展开子块内容 | 议程块 |
| **LinkPreview** | 链接 | 链接预览 |
| **SyncSource/SyncReference** | 展开子块内容 | 同步块 |
| **WikiCatalogV2** | `[知识库目录 V2]` | |
| **AITemplate** | HTML 注释 | AI 模板块 |

### Callout 高亮块导出

Callout 块（飞书高亮块）导出为 GitHub-style alert 语法：

```markdown
> [!NOTE]
> 这是一个提示信息。

> [!WARNING]
> 这是一个警告信息。
```

支持 6 种 Callout 类型（按背景色映射）：

| 背景色 | 导出类型 | 说明 |
|--------|---------|------|
| 2 (红色) | `[!WARNING]` | 警告 |
| 3 (橙色) | `[!CAUTION]` | 警示 |
| 4 (黄色) | `[!TIP]` | 技巧 |
| 5 (绿色) | `[!SUCCESS]` | 成功 |
| 6 (蓝色) | `[!NOTE]` | 提示 |
| 7 (紫色) | `[!IMPORTANT]` | 重要 |

Callout 内部子块（段落、列表等）会在引用语法内逐行展示。

### 公式导出

- **块级公式**：独立行 `$formula$`
- **行内公式**：段落内嵌 `$E = mc^2$`
- 公式内容保持 LaTeX 原文，不做转义

### 特殊字符处理

导出时自动处理以下 Markdown 特殊字符：
- 普通文本中的 `* _ [ ] # ~ $ > |` 会自动添加 `\` 转义
- 代码块内的文本不做转义（使用原始文本）
- 表格单元格中的 `|` 会转义为 `\|`
- URL 中的括号 `(` `)` 会编码为 `%28` `%29`

## 已验证功能

以下导出功能已通过测试验证：
- 普通文档导出 ✅
- 知识库文档导出 ✅
- 标题、段落、列表（含嵌套列表）、代码块、引用、分割线 ✅
- 任务列表（Todo）✅
- **图片下载** ✅（使用 `--download-images`）
- **Callout 高亮块**（6 种类型）✅
- **公式**（块级 + 行内）✅
- **Front Matter** ✅（使用 `--front-matter`）
- **文本高亮颜色** ✅（使用 `--highlight`）
- **ISV 块**（Mermaid 绘图）✅
- **AddOns/SyncedBlock 展开** ✅
- **特殊字符转义** ✅
- **@用户展开** ✅（使用 `--expand-mentions`，默认开启）
- **新块类型**（Agenda/LinkPreview/SyncBlock/WikiCatalogV2/AITemplate）✅
- 表格结构 ⚠️（内容可能丢失）
- 飞书画板 → 画板链接/PNG 图片 ✅

## 双向转换说明

| 导入（Markdown → 飞书） | 导出（飞书 → Markdown） |
|------------------------|------------------------|
| Mermaid/PlantUML 代码块 → 飞书画板 | 飞书画板 → 画板链接/PNG 图片 |
| 大表格 → 自动拆分为多个表格 | 多个表格 → 分开的表格 |
| 缩进列表 → 嵌套父子块 | 嵌套列表 → 缩进 Markdown |
| `> [!NOTE]` → Callout 高亮块 | Callout 高亮块 → `> [!NOTE]` |
| `$formula$` → 行内公式 | 行内/块级公式 → `$formula$` |
| `<u>下划线</u>` → 下划线样式 | 下划线样式 → `<u>下划线</u>` |

**注意**：Mermaid/PlantUML 图表导入后会转换为飞书画板，导出时生成的是画板链接而非原始图表代码。

---

## 异步导出为 PDF/Word/Excel（doc export-file）

将飞书云文档导出为 PDF、Word 等格式（异步三步流程）：

### 执行流程

```bash
# 一条命令完成全部流程（内部自动创建任务→轮询→下载）
feishu-cli doc export-file <doc_token> --type pdf -o output.pdf
```

### 支持的导出格式

| --type | 格式 | 说明 |
|--------|------|------|
| `pdf` | PDF | 保留排版 |
| `docx` | Word | 可编辑 |

### 参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `<doc_token>` | 文档 Token | 必填 |
| `--type` | 导出格式 | 必填 |
| `-o, --output` | 输出文件路径 | 必填 |

### 示例

```bash
# 导出为 PDF
feishu-cli doc export-file JKbxdRez1oNWEKxPz14cWMpBnKh --type pdf -o /tmp/report.pdf

# 导出为 Word
feishu-cli doc export-file JKbxdRez1oNWEKxPz14cWMpBnKh --type docx -o /tmp/report.docx
```

---

## 从本地文件导入为飞书云文档（doc import-file）

将本地 DOCX/XLSX 等文件导入为飞书云文档（异步流程）：

### 执行流程

```bash
# 一条命令完成全部流程（内部自动上传→创建任务→轮询）
feishu-cli doc import-file local_file.docx --type docx --name "文档名称"
```

### 支持的导入格式

| --type | 格式 | 说明 |
|--------|------|------|
| `docx` | Word 文档 | 转换为飞书文档 |

### 参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `<local_path>` | 本地文件路径 | 必填 |
| `--type` | 文件类型 | 必填 |
| `--name` | 飞书文档名称 | 文件名 |

### 示例

```bash
# 导入 Word 文档
feishu-cli doc import-file ~/Documents/report.docx --type docx --name "季度报告"
```
