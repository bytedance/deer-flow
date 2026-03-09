# 画板操作详细参考

## 下载画板图片

将画板导出为 PNG 图片：

```bash
feishu-cli board image <whiteboard_id> output.png
```

## 导入图表到画板

### 从文件导入

```bash
# PlantUML 文件（默认）
feishu-cli board import <whiteboard_id> diagram.puml

# Mermaid 文件
feishu-cli board import <whiteboard_id> diagram.mmd --syntax mermaid

# 指定图表类型
feishu-cli board import <whiteboard_id> diagram.puml --diagram-type 2
```

### 从内容直接导入

```bash
feishu-cli board import <whiteboard_id> \
  --source-type content \
  -c "graph TD; A-->B" \
  --syntax mermaid
```

### 导入参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--syntax` | `plantuml` 或 `mermaid` | `plantuml` |
| `--diagram-type` | 图表类型编号（见下表） | `0`（auto） |
| `--style` | `board` 或 `classic` | `board` |
| `--source-type` | `file` 或 `content` | `file` |
| `-c, --content` | 当 source-type=content 时的图表内容 | — |

### diagram-type 映射

| 编号 | 类型 | 说明 |
|------|------|------|
| 0 | auto | 自动检测 |
| 1 | mindmap | 思维导图 |
| 2 | sequence | 时序图 |
| 3 | activity | 活动图 |
| 4 | class | 类图 |
| 5 | er | ER 图 |
| 6 | flowchart | 流程图 |
| 7 | state | 状态图 |
| 8 | component | 组件图 |

## 获取画板节点

```bash
feishu-cli board nodes <whiteboard_id>
```

## 在文档中添加画板

```bash
# 在文档末尾添加空白画板
feishu-cli doc add-board <document_id>

# 在指定位置添加
feishu-cli doc add-board <document_id> --parent-id <block_id> --index 0
```

## 支持的 Mermaid 图表类型

以下 8 种类型全部经过实际验证：

| 类型 | diagram_type | 验证状态 |
|------|-------------|---------|
| flowchart | 6 | 通过（支持 subgraph） |
| sequenceDiagram | 2 | 通过 |
| classDiagram | 4 | 通过 |
| stateDiagram-v2 | 0（auto） | 通过 |
| erDiagram | 5 | 通过 |
| gantt | 0（auto） | 通过 |
| pie | 0（auto） | 通过 |
| mindmap | 1 | 通过 |

## 画板 API 技术说明

- API 端点：`/open-apis/board/v1/whiteboards/{id}/nodes/plantuml`
- `syntax_type=1` 表示 PlantUML，`syntax_type=2` 表示 Mermaid
- 使用通用 HTTP 请求方式（client.Get/Post），非专用 SDK 方法

## 权限要求

| 权限 | 说明 |
|------|------|
| `board:board` | 画板操作 |
| `docx:document` | 文档中添加画板 |

## 已知限制

| 限制 | 说明 |
|------|------|
| `board import` CLI 命令 | 单独导入画板时 API 返回 404（API 限制） |
| `board create-notes` | API 格式问题（API 限制） |
| Mermaid 花括号 | `{text}` 被识别为菱形节点，需避免 |
| Mermaid par 语法 | `par...and...end` 飞书不支持 |
