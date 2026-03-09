# 电子表格详细参考

## API 版本说明

| API 版本 | 用途 | 数据格式 |
|---------|------|---------|
| V2 | 基础读写（简单数据） | 二维数组 `[["A1","B1"],["A2","B2"]]` |
| V3 | 富文本读写（格式化数据） | 三维数组 `[[[[{"type":"text","text":{"text":"Hello"}}]]]]` |

## V2 API 命令

### 读取单元格

```bash
feishu-cli sheet read <token> "Sheet1!A1:C10"
feishu-cli sheet read <token> "Sheet1!A:C"      # 整列
feishu-cli sheet read <token> "Sheet1!1:3"       # 整行
```

### 写入单元格

```bash
feishu-cli sheet write <token> "Sheet1!A1:B2" --data '[["姓名","年龄"],["张三",25]]'
```

### 追加数据

```bash
feishu-cli sheet append <token> "Sheet1!A:B" --data '[["新数据1","新数据2"]]'
```

## V3 API 命令

### 读取（纯文本/富文本）

```bash
# 纯文本模式
feishu-cli sheet read-plain <token> <sheet_id> "Sheet1!A1:C10"

# 富文本模式（返回完整格式信息）
feishu-cli sheet read-rich <token> <sheet_id> "Sheet1!A1:C10"
```

### 写入富文本

```bash
feishu-cli sheet write-rich <token> <sheet_id> --data-file data.json
```

data.json 格式示例（三维数组）：
```json
{
  "range": "Sheet1!A1:B2",
  "values": [
    [
      [{"type": "text", "text": {"text": "加粗文本"}, "textStyle": {"bold": true}}],
      [{"type": "text", "text": {"text": "普通文本"}}]
    ],
    [
      [{"type": "link", "link": {"text": "飞书", "url": "https://feishu.cn"}}],
      [{"type": "formula", "formula": {"text": "=SUM(A1:A10)"}}]
    ]
  ]
}
```

### V3 富文本元素类型

| 类型 | 说明 | 主要字段 |
|------|------|---------|
| `text` | 文本 | `text.text`, `textStyle.bold/italic/underline/strikethrough` |
| `value` | 数值 | `value` |
| `date_time` | 日期时间 | `dateTime` |
| `mention_user` | @用户 | `mentionUser.userId` |
| `mention_document` | @文档 | `mentionDocument.token`, `mentionDocument.objType` |
| `image` | 图片 | `image.token` |
| `file` | 文件 | `file.token` |
| `link` | 链接 | `link.text`, `link.url` |
| `formula` | 公式 | `formula.text` |
| `reminder` | 提醒 | `reminder` |

### 插入/追加/清除（V3）

```bash
# 在指定位置插入数据
feishu-cli sheet insert <token> <sheet_id> --data-file data.json

# 追加富文本
feishu-cli sheet append-rich <token> <sheet_id> --data-file data.json

# 清除范围内容
feishu-cli sheet clear <token> <sheet_id> "Sheet1!A1:C10"
```

## 行列操作

```bash
# 添加行/列
feishu-cli sheet add-rows <token> <sheet_id> --count 5
feishu-cli sheet add-cols <token> <sheet_id> --count 3

# 在指定位置插入行
feishu-cli sheet insert-rows <token> <sheet_id> --start 2 --count 3

# 删除行/列
feishu-cli sheet delete-rows <token> <sheet_id> --start 2 --end 5
feishu-cli sheet delete-cols <token> <sheet_id> --start 1 --end 3
```

## 样式设置

```bash
feishu-cli sheet style <token> "Sheet1!A1:C3" \
  --bold \
  --italic \
  --bg-color "#FFFF00" \
  --fg-color "#FF0000"
```

## 合并/拆分单元格

```bash
feishu-cli sheet merge <token> "Sheet1!A1:B2"
feishu-cli sheet unmerge <token> "Sheet1!A1:B2"
```

## 查找替换

```bash
feishu-cli sheet find <token> <sheet_id> --find "关键词"
feishu-cli sheet replace <token> <sheet_id> --find "旧文本" --replace "新文本"
```

## 工作表管理

```bash
# 添加/删除/复制工作表
feishu-cli sheet add-sheet <token> --title "新工作表"
feishu-cli sheet delete-sheet <token> <sheet_id>
feishu-cli sheet copy-sheet <token> <sheet_id> [--title "副本"]
```

## 单元格图片

```bash
# 需要先通过 media upload 获取 image_token
feishu-cli sheet image <token> "Sheet1!A1" --image-token <token>
```

## 工作表保护

```bash
feishu-cli sheet protect <token> <sheet_id> [--lock/--unlock]
```

> 已知问题：V2 API 可能返回 "invalid operation"。

## API 限制

| 限制 | 说明 |
|------|------|
| 单次写入 | 最多 5000 个单元格 |
| 单元格内容 | 最大 50000 字符 |
| 频率限制 | 100 次/分钟 |
| V3 写入 | 单次最多 10 个范围 |
| 范围格式 | `SheetID!A1:C10`，支持整列 `A:C` 和整行 `1:3` |
