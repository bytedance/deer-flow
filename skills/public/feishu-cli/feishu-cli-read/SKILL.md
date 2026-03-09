---
name: feishu-cli-read
description: >-
  读取飞书云文档或知识库内容，分析文档结构。当用户请求"查看"、"阅读"、"分析"、"读取"、
  "打开"飞书文档或知识库时使用。支持通过文档 ID、知识库 Token 或 URL 读取。
  Markdown 作为中间格式存储在 /tmp 目录。
argument-hint: <document_id|node_token|url>
user-invocable: true
allowed-tools: Bash, Read, Grep
---

# 飞书文档阅读技能

从飞书云文档或知识库读取内容，转换为 Markdown 格式后进行分析和展示。

## 核心概念

**Markdown 作为中间态**：本地文档与飞书云文档之间通过 Markdown 格式进行转换，中间文件存储在 `/tmp` 目录中。

## 使用方法

```bash
/feishu-read <document_id>
/feishu-read <node_token>
/feishu-read <url>
```

## 执行流程

1. **解析参数**
   - 判断 URL 类型：
     - `/docx/` → 普通文档，使用 `doc export`
     - `/wiki/` → 知识库文档，使用 `wiki export`
   - 如果是 Token，根据格式判断类型

2. **导出为 Markdown（含图片下载）**

   **普通文档**:
   ```bash
   feishu-cli doc export <document_id> --output /tmp/feishu_doc.md --download-images --assets-dir /tmp/feishu_assets
   ```

   **知识库文档**:
   ```bash
   feishu-cli wiki export <node_token> --output /tmp/feishu_wiki.md --download-images --assets-dir /tmp/feishu_assets
   ```

   **重要**：务必使用 `--download-images` 参数下载文档中的图片到本地。

   **可选参数**：
   - `--front-matter`：在 Markdown 顶部添加 YAML front matter（含标题和文档 ID）
   - `--highlight`：保留文本颜色和背景色（输出为 HTML `<span>` 标签）
   - `--expand-mentions`：展开 @用户为友好格式（默认开启，需要 contact:user.base:readonly 权限）

3. **读取文本内容**
   - 使用 Read 工具读取导出的 Markdown 文件
   - 分析文档结构和文本内容

4. **读取并理解图片内容**
   - 检查 `/tmp/feishu_assets` 目录是否有下载的图片
   - **使用 Read 工具逐个读取图片文件**，理解图片内容
   - 将图片内容整合到文档分析中

   ```bash
   # 列出下载的图片
   ls /tmp/feishu_assets/

   # 使用 Read 工具查看图片（Claude 支持多模态）
   # Read /tmp/feishu_assets/image_1.png
   ```

5. **报告结果**
   - 提供文档摘要（包含图片内容描述）
   - 保留 Markdown 文件和图片供用户进一步操作

## 输出格式

向用户报告：
- 文档标题
- 文档结构概要（标题层级）
- 内容摘要（关键信息）
- **图片内容描述**（如有图片）
- Markdown 文件路径（供后续使用）
- 图片文件路径（如有下载）

## 支持的 URL 格式

| URL 格式 | 类型 | 命令 |
|---------|------|------|
| `https://xxx.feishu.cn/docx/<id>` | 普通文档 | `doc export` |
| `https://xxx.feishu.cn/wiki/<token>` | 知识库 | `wiki export` |
| `https://xxx.larkoffice.com/docx/<id>` | 普通文档 | `doc export` |
| `https://xxx.larkoffice.com/wiki/<token>` | 知识库 | `wiki export` |

## 示例

```bash
# 读取普通文档
/feishu-read <document_id>
/feishu-read https://xxx.feishu.cn/docx/<document_id>

# 读取知识库文档
/feishu-read <node_token>
/feishu-read https://xxx.feishu.cn/wiki/<node_token>
```

## 图片处理流程（重要）

文档中的图片需要特别处理才能理解其内容：

### 步骤 1：导出时下载图片

```bash
# 知识库文档
feishu-cli wiki export <node_token> \
  --output /tmp/doc.md \
  --download-images \
  --assets-dir /tmp/doc_assets

# 普通文档
feishu-cli doc export <document_id> \
  --output /tmp/doc.md \
  --download-images \
  --assets-dir /tmp/doc_assets
```

### 步骤 2：检查下载的图片

```bash
ls -la /tmp/doc_assets/
# 输出示例：
# image_1.png  (403KB)
# image_2.png  (394KB)
```

### 步骤 3：使用 Read 工具查看图片

Claude 支持多模态，可以直接理解图片内容：

```
# 在 Claude 中使用 Read 工具读取图片
Read /tmp/doc_assets/image_1.png
Read /tmp/doc_assets/image_2.png
```

### 步骤 4：整合分析

将图片内容与文档文本结合，提供完整的文档分析。

## 完整示例

```bash
# 1. 导出文档和图片
feishu-cli wiki export <node_token> \
  -o /tmp/wiki_doc.md \
  --download-images \
  --assets-dir /tmp/wiki_assets

# 2. 查看图片列表
ls /tmp/wiki_assets/

# 3. 读取 Markdown 内容
# Read /tmp/wiki_doc.md

# 4. 读取每张图片理解内容
# Read /tmp/wiki_assets/image_1.png
# Read /tmp/wiki_assets/image_2.png

# 5. 综合分析后向用户报告
```

## 目录节点识别与处理

知识库文档可能是**目录节点**（包含子节点），通过以下方式识别：

### 1. 识别目录节点

当导出知识库文档时，如果 Markdown 内容显示为：
```markdown
[Wiki 目录 - 使用 'wiki nodes <space_id> --parent <node_token>' 获取子节点列表]
```

说明这是一个**Wiki 目录节点**（block_type=42），子文档列表存储在知识库元数据中。

### 2. 获取子节点列表

```bash
# 1. 先获取节点信息，记录 space_id
feishu-cli wiki get <node_token>

# 2. 列出该节点下的子节点
feishu-cli wiki nodes <space_id> --parent <node_token>
```

### 3. 完整处理流程

```bash
# 步骤 1：尝试导出文档
feishu-cli wiki export <node_token> -o /tmp/doc.md

# 步骤 2：检查内容
# 如果显示 "[Wiki 目录...]"，说明是目录节点

# 步骤 3：获取节点信息
feishu-cli wiki get <node_token>
# 记录 space_id 和 has_child 字段

# 步骤 4：获取子节点
feishu-cli wiki nodes <space_id> --parent <node_token>

# 步骤 5：逐个导出子节点
feishu-cli wiki export <child_node_token_1> -o /tmp/child1.md
feishu-cli wiki export <child_node_token_2> -o /tmp/child2.md
```

## 错误处理与边界情况

### 1. 常见错误

| 错误 | 原因 | 解决 |
|------|------|------|
| `code=131002, param err` | 参数错误 | 检查 token 格式 |
| `code=131001, node not found` | 节点不存在 | 检查 token 是否正确 |
| `code=131003, no permission` | 无权限访问 | 确认应用有 wiki:wiki:readonly 权限 |
| `code=131004, space not found` | 知识空间不存在 | 检查 space_id 是否正确 |
| 空内容或 `Unknown block type` | 特殊块类型 | 见「目录节点识别」章节 |

### 2. 边界情况处理

**情况 1：文档内容为空**
- 检查文档是否真的为空
- 检查是否有权限查看内容
- 检查是否是目录节点（见上文）

**情况 2：图片下载失败**
- 检查 `--assets-dir` 目录是否可写
- 检查网络连接
- 图片可能已被删除或过期

**情况 3：部分块类型无法识别**
- 飞书 API 可能返回未知的块类型
- 这些块会显示为 `<!-- Unknown block type: XX -->`
- 这是正常现象，不影响其他内容的读取

**情况 4：大型文档**
- 超过 1000 个块的文档可能需要分页获取
- 使用 `feishu-cli doc blocks <doc_id> --all` 自动分页

### 3. 重试机制

如果遇到网络错误或 API 限流：

```bash
# 添加 --debug 查看详细错误信息
feishu-cli wiki export <token> --debug

# 等待几秒后重试
sleep 5 && feishu-cli wiki export <token>
```

## 导出格式说明

导出的 Markdown 支持以下飞书特有块类型的转换：

| 飞书块类型 | Markdown 表现 |
|-----------|--------------|
| Callout 高亮块 | `> [!NOTE]`、`> [!WARNING]` 等 6 种 GitHub-style alert |
| 块级/行内公式 | `$formula$`（LaTeX 格式） |
| 画板 (Board) | `[画板/Whiteboard](feishu://board/...)` 链接 |
| ISV 块 (Mermaid) | 画板链接 |
| QuoteContainer | `>` 引用语法（支持嵌套） |
| AddOns/SyncedBlock | 透明展开子块内容 |
| Iframe | `<iframe>` HTML 标签 |

使用 `--highlight` 参数时，带颜色的文本输出为 `<span style="color:...">` 标签。

## 注意事项

1. **务必下载图片**：不下载图片只能看到 `feishu://media/<token>` 引用，无法理解图片内容
2. **逐个读取图片**：使用 Read 工具读取每张图片，Claude 会自动理解图片内容
3. **整合分析**：将图片描述与文档文本结合，提供完整的内容摘要
4. **识别目录节点**：目录节点的内容是子节点列表，不是实际文档内容
5. **公式内容**：导出的 LaTeX 公式保持原文，可直接被 Markdown 渲染器显示
6. **Callout 类型**：支持 NOTE/WARNING/TIP/CAUTION/IMPORTANT/SUCCESS 六种高亮块类型
