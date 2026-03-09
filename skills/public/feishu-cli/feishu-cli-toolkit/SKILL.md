---
name: feishu-cli-toolkit
description: >-
  飞书综合工具箱：电子表格、日历日程、任务管理、群聊管理、画板操作、PlantUML 图表、
  文件管理、素材上传下载、文档评论、知识库、搜索、用户通讯录。当用户请求操作飞书表格、
  查看日历、创建任务、管理群聊、操作画板、生成 PlantUML、管理文件、上传素材、
  查看评论、查看知识库、搜索消息、查询用户信息、查询部门时使用。
  涵盖 feishu-cli 除文档读写导入导出和权限管理外的全部功能。
argument-hint: <module> <command> [args]
user-invocable: true
allowed-tools: Bash, Read, Write
---

# 飞书综合工具箱

覆盖 feishu-cli 的 12 个功能模块，提供命令速查和核心用法。复杂模块的详细参考文档在 `references/` 目录中。

## 模块速查表

| # | 模块 | 核心命令 | 详细参考 |
|---|------|---------|---------|
| 1 | 电子表格 | `sheet create/get/read/write/append` + V3 富文本 | `references/sheet-commands.md` |
| 2 | 日历日程 | `calendar list/get/primary/create-event/event-search/freebusy` | `references/calendar-commands.md` |
| 3 | 任务管理 | `task create/complete/delete` + subtask/member/reminder + `tasklist` | `references/task-commands.md` |
| 4 | 群聊管理 | `chat create/get/update/delete/link` + `chat member` | `references/chat-commands.md` |
| 5 | 画板操作 | `board image/import/nodes` + `doc add-board` | `references/board-commands.md` |
| 6 | PlantUML | 飞书画板安全子集语法 | `references/plantuml-safe-subset.md` |
| 7 | 文件管理 | `file list/mkdir/move/copy/delete/download/upload/version/meta/stats` | — |
| 8 | 素材管理 | `media upload/download` | — |
| 9 | 评论管理 | `comment list/add/delete/resolve/unresolve` + `comment reply` | — |
| 10 | 知识库 | `wiki get/export/spaces/nodes/space-get` + `wiki member` | — |
| 11 | 搜索 | `search messages/apps`（需 User Access Token） | `references/search-commands.md` |
| 12 | 用户和部门 | `user info/search/list` + `dept get/children` | — |

---

## 1. 电子表格

支持 V2（简单二维数组）和 V3（富文本三维数组）两套 API。

### 常用命令

```bash
# 创建表格
feishu-cli sheet create --title "新表格"

# 获取表格信息
feishu-cli sheet get <token>

# 列出工作表
feishu-cli sheet list-sheets <token>

# V2 读写（二维数组）
feishu-cli sheet read <token> "Sheet1!A1:C10"
feishu-cli sheet write <token> "Sheet1!A1:B2" --data '[["姓名","年龄"],["张三",25]]'
feishu-cli sheet append <token> "Sheet1!A:B" --data '[["新行1","新行2"]]'

# V3 富文本读写（三维数组）
feishu-cli sheet read-plain <token> <sheet_id> "Sheet1!A1:C10"
feishu-cli sheet read-rich <token> <sheet_id> "Sheet1!A1:C10"
feishu-cli sheet write-rich <token> <sheet_id> --data-file data.json

# 行列操作
feishu-cli sheet add-rows <token> <sheet_id> --count 5
feishu-cli sheet add-cols <token> <sheet_id> --count 3
feishu-cli sheet delete-rows <token> <sheet_id> --start 2 --end 5
feishu-cli sheet delete-cols <token> <sheet_id> --start 1 --end 3

# 样式和格式
feishu-cli sheet merge <token> "Sheet1!A1:B2"
feishu-cli sheet unmerge <token> "Sheet1!A1:B2"
feishu-cli sheet style <token> "Sheet1!A1:C3" --bold --bg-color "#FF0000"

# 查找替换
feishu-cli sheet find <token> <sheet_id> --find "旧文本"
feishu-cli sheet replace <token> <sheet_id> --find "旧文本" --replace "新文本"
```

### API 限制

- 单次写入最多 5000 个单元格，单元格最大 50000 字符
- V2 范围格式：`SheetID!A1:C10`，支持整列 `A:C` 和整行 `1:3`
- V3 写入限制：单次最多 10 个范围

**详细参考**：读取 `references/sheet-commands.md` 获取 V3 富文本格式、工作表管理、单元格图片等完整说明。

**权限要求**：`sheets:spreadsheet`

---

## 2. 日历和日程

管理飞书日历、日程、参与人和忙闲查询。时间格式统一使用 RFC3339（如 `2024-01-01T10:00:00+08:00`）。

### 常用命令

```bash
# 日历
feishu-cli calendar list                    # 列出日历
feishu-cli calendar get <calendar_id>       # 获取日历详情
feishu-cli calendar primary                 # 获取主日历

# 日程 CRUD
feishu-cli calendar create-event \
  --calendar-id <id> \
  --summary "团队周会" \
  --start "2024-01-21T14:00:00+08:00" \
  --end "2024-01-21T15:00:00+08:00" \
  --description "讨论本周进展"

feishu-cli calendar list-events --calendar-id <id> --start <RFC3339> --end <RFC3339>
feishu-cli calendar get-event --calendar-id <id> --event-id <event_id>
feishu-cli calendar update-event --calendar-id <id> --event-id <event_id> --summary "新标题"
feishu-cli calendar delete-event --calendar-id <id> --event-id <event_id>

# 搜索日程
feishu-cli calendar event-search --calendar-id <id> --query "周会"

# 回复日程邀请
feishu-cli calendar event-reply <calendar_id> <event_id> --status accept   # accept/decline/tentative

# 参与人管理
feishu-cli calendar attendee add <calendar_id> <event_id> --user-ids id1,id2
feishu-cli calendar attendee list <calendar_id> <event_id>

# 忙闲查询
feishu-cli calendar freebusy \
  --start "2024-01-01T00:00:00+08:00" \
  --end "2024-01-02T00:00:00+08:00" \
  --user-id <user_id>
```

**详细参考**：读取 `references/calendar-commands.md` 获取完整参数说明。

**权限要求**：`calendar:calendar:readonly`（读取），`calendar:calendar`（写操作，需单独申请）

---

## 3. 任务管理

管理飞书任务（V2 API），包括子任务、成员、提醒和任务清单。任务 ID 为 UUID 格式。

### 常用命令

```bash
# 任务 CRUD
feishu-cli task create --summary "完成代码审查" --description "详细描述" --due "2024-02-01"
feishu-cli task list [--completed | --uncompleted]
feishu-cli task get <task_id>
feishu-cli task update <task_id> --summary "新标题"
feishu-cli task complete <task_id>
feishu-cli task delete <task_id>

# 子任务
feishu-cli task subtask create <task_guid> --summary "子任务标题"
feishu-cli task subtask list <task_guid>

# 成员管理
feishu-cli task member add <task_guid> --members id1,id2 --role assignee    # assignee/follower
feishu-cli task member remove <task_guid> --members id1,id2 --role assignee

# 提醒
feishu-cli task reminder add <task_guid> --minutes 30     # 提前 30 分钟提醒，0=截止时
feishu-cli task reminder remove <task_guid> --ids id1,id2

# 任务清单
feishu-cli tasklist create --name "Sprint 计划"
feishu-cli tasklist list
feishu-cli tasklist get <tasklist_guid>
feishu-cli tasklist delete <tasklist_guid>
```

**详细参考**：读取 `references/task-commands.md` 获取完整参数说明。

**权限要求**：`task:task:read`、`task:task:write`、`task:tasklist:read`、`task:tasklist:write`（需单独申请）

---

## 4. 群聊管理

创建/管理群聊，管理群成员。

### 常用命令

```bash
# 群聊 CRUD
feishu-cli chat create --name "项目群" --user-ids id1,id2 [--chat-type private|public]
feishu-cli chat get <chat_id>
feishu-cli chat update <chat_id> --name "新群名" [--description "新描述"]
feishu-cli chat delete <chat_id>

# 获取群分享链接
feishu-cli chat link <chat_id> [--validity-period week|year|permanently]

# 群成员管理
feishu-cli chat member list <chat_id> [--member-id-type open_id|user_id|union_id]
feishu-cli chat member add <chat_id> --id-list id1,id2 [--member-id-type open_id]
feishu-cli chat member remove <chat_id> --id-list id1,id2 [--member-id-type open_id]
```

**详细参考**：读取 `references/chat-commands.md` 获取完整参数和示例。

**权限要求**：`im:chat`（群聊管理）、`im:chat:readonly`（读取）、`im:chat:member`（成员操作）

---

## 5. 画板操作

下载画板图片、导入 Mermaid/PlantUML 图表到画板。

### 常用命令

```bash
# 下载画板为 PNG 图片
feishu-cli board image <whiteboard_id> output.png

# 导入图表到画板
feishu-cli board import <whiteboard_id> diagram.puml                              # PlantUML 文件
feishu-cli board import <whiteboard_id> diagram.mmd --syntax mermaid              # Mermaid 文件
feishu-cli board import <whiteboard_id> --source-type content -c "graph TD; A-->B" --syntax mermaid  # 内容直接导入

# 获取画板节点列表
feishu-cli board nodes <whiteboard_id>

# 在文档中添加空白画板
feishu-cli doc add-board <document_id> [--parent-id <block_id> --index 0]
```

### 图表导入参数

| 参数 | 说明 |
|------|------|
| `--syntax` | `plantuml`（默认）或 `mermaid` |
| `--diagram-type` | 0=auto, 1=mindmap, 2=sequence, 3=activity, 4=class, 5=er, 6=flowchart, 7=state, 8=component |
| `--style` | `board`（默认）或 `classic` |
| `--source-type` | `file`（默认）或 `content` |
| `-c, --content` | 当 source-type=content 时的图表内容 |

### 支持的 Mermaid 类型（8 种，全部已验证）

flowchart、sequenceDiagram、classDiagram、stateDiagram-v2、erDiagram、gantt、pie、mindmap

**详细参考**：读取 `references/board-commands.md` 获取完整说明。

**权限要求**：`board:board`（画板操作）、`docx:document`（文档画板）

---

## 6. PlantUML 图表生成

生成适配飞书画板的 PlantUML 图表。**默认推荐 Mermaid**（飞书原生支持更好），仅在 Mermaid 不支持的图类型（用例图、组件图、复杂活动图）时才用 PlantUML。

### 安全子集核心规则

- 必须使用 `@startuml`/`@enduml` 包裹（思维导图用 `@startmindmap`/`@endmindmap`）
- **不要使用行首缩进**（飞书画板将缩进行视为独立行）
- 避免 `skinparam`、`!define`、颜色/字体/对齐控制、方向控制指令
- 类图避免可见性标记（`+ - # ~`），用 `field : type` 或 `method()` 格式

### 支持的图类型

活动图/流程图、时序图、类图、用例图、组件图、ER 图、思维导图

### 导入方式

1. 在 Markdown 中使用 ` ```plantuml ` 代码块，通过 `feishu-cli doc import` 导入
2. 直接通过 `board import` 命令导入到画板

**详细参考**：读取 `references/plantuml-safe-subset.md` 获取每种图类型的安全语法规范。

---

## 7. 文件管理

飞书云空间（Drive）文件的完整管理，包括文件 CRUD、版本管理、元数据和统计。

### 常用命令

```bash
# 列出文件
feishu-cli file list [folder_token]

# 创建文件夹
feishu-cli file mkdir "文件夹名" [--parent <folder_token>]

# 移动/复制/删除
feishu-cli file move <file_token> --target <folder_token> --type <docx|sheet|file|...>
feishu-cli file copy <file_token> --target <folder_token> --type <type> [--name "新名"]
feishu-cli file delete <file_token> --type <type>    # 移到回收站，30 天可恢复

# 下载/上传
feishu-cli file download <file_token> -o output.pdf
feishu-cli file upload local_file.pdf --parent <FOLDER_TOKEN> [--name "自定义名"]

# 版本管理
feishu-cli file version list <file_token> [--obj-type docx]
feishu-cli file version create <file_token> --name "v1.0" [--obj-type docx]
feishu-cli file version get <file_token> <version_id>
feishu-cli file version delete <file_token> <version_id>

# 元数据和统计
feishu-cli file meta TOKEN1 TOKEN2 --doc-type docx       # 批量获取元数据
feishu-cli file stats <file_token> --doc-type docx        # 获取统计信息
```

### 文件类型

`docx`、`doc`、`sheet`、`bitable`、`mindnote`、`folder`、`file`

**权限要求**：`drive:drive:readonly`（读取）、`drive:drive`（写操作）

---

## 8. 素材管理

上传图片/文件到飞书云空间，或下载已有素材。

### 常用命令

```bash
# 上传素材（用于文档中的图片/附件）
feishu-cli media upload image.png \
  --parent-type docx_image \
  --parent-node <doc_id>

# 下载素材
feishu-cli media download <file_token> -o output.png
```

### parent-type 参数说明

| 值 | 说明 |
|---|------|
| `docx_image` | 新版文档图片（默认） |
| `docx_file` | 新版文档附件 |
| `doc_image` | 旧版文档图片 |
| `doc_file` | 旧版文档附件 |
| `sheet_image` | 电子表格图片 |
| `comment_image` | 评论图片 |

### 限制

- 图片最大 20MB，支持 PNG/JPG/JPEG/GIF/BMP/SVG/WEBP
- 文件最大 512MB，支持 PDF/DOC/DOCX/XLS/XLSX/PPT/PPTX/ZIP 等

**权限要求**：`drive:drive:readonly`（下载）、`drive:drive`（上传）

---

## 9. 评论管理

管理飞书云文档的评论，包括全文评论、评论解决/取消解决、回复管理。

### 常用命令

```bash
# 列出评论
feishu-cli comment list <file_token> --type docx

# 添加全文评论
feishu-cli comment add <file_token> --type docx --text "评论内容"

# 删除评论（不可逆）
feishu-cli comment delete <file_token> <comment_id> --type docx

# 解决/取消解决评论
feishu-cli comment resolve <file_token> <comment_id> --type docx
feishu-cli comment unresolve <file_token> <comment_id> --type docx

# 回复管理
feishu-cli comment reply list <file_token> <comment_id> --type docx
feishu-cli comment reply delete <file_token> <comment_id> <reply_id> --type docx
```

### 支持的文件类型

`--type` 参数支持：`docx`、`doc`、`sheet`、`bitable`

**权限要求**：`drive:drive.comment:readonly`（读取）、`drive:drive.comment:write`（写入）

---

## 10. 知识库

查看知识空间、获取知识库节点、导出知识库文档、管理空间成员。

### 常用命令

```bash
# 获取节点信息（支持 URL 或 token）
feishu-cli wiki get <node_token>

# 导出为 Markdown
feishu-cli wiki export <node_token> -o doc.md [--download-images --assets-dir ./assets]

# 列出知识空间
feishu-cli wiki spaces [--page-size 20]

# 列出空间下的节点
feishu-cli wiki nodes <space_id> [--parent <node_token>]

# 获取空间详情
feishu-cli wiki space-get <space_id>

# 空间成员管理
feishu-cli wiki member add <space_id> --member-type userid --member-id <USER_ID> --role admin
feishu-cli wiki member list <space_id>
feishu-cli wiki member remove <space_id> --member-type userid --member-id <USER_ID> --role admin
```

### 重要概念

- 知识库使用 `node_token`（区别于普通文档的 `document_id`）
- 目录节点导出内容为 `[Wiki 目录...]`，需用 `wiki nodes` 获取子节点
- 成员角色：`admin`（管理员）、`member`（成员）
- 成员类型：`openchat`、`userid`、`email`、`opendepartmentid`、`openid`

**权限要求**：`wiki:wiki:readonly`（读取）、`wiki:wiki`（空间成员管理）

---

## 11. 搜索

搜索飞书消息和应用。**重要：需要 User Access Token**（非 App Access Token）。

### 常用命令

```bash
# 搜索消息
feishu-cli search messages "关键词" \
  --user-access-token <token> \
  [--chat-ids oc_xxx] \
  [--message-type file|image|media] \
  [--chat-type group_chat|p2p_chat] \
  [--from-type bot|user] \
  [--start-time 1704067200] \
  [--end-time 1704153600]

# 搜索应用
feishu-cli search apps "应用名" --user-access-token <token>
```

### User Access Token 说明

- 通过 `--user-access-token` 参数或 `FEISHU_USER_ACCESS_TOKEN` 环境变量提供
- Token 有效期约 2 小时，Refresh Token 有效期 30 天
- 不能使用 App Access Token（会报权限错误）

**详细参考**：读取 `references/search-commands.md` 获取完整筛选参数说明。

---

## 12. 用户和部门

查询用户信息、通过邮箱/手机号查找用户、列出部门成员和子部门。

### 常用命令

```bash
# 获取用户信息
feishu-cli user info <user_id> [--user-id-type open_id|union_id|user_id]

# 通过邮箱/手机号查询用户 ID
feishu-cli user search --email user@example.com
feishu-cli user search --mobile 13800138000
feishu-cli user search --email "a@example.com,b@example.com"    # 批量查询

# 列出部门下的用户
feishu-cli user list --department-id <dept_id> [--user-id-type open_id]

# 获取部门详情
feishu-cli dept get <department_id> [--department-id-type open_department_id]

# 获取子部门列表（根部门使用 "0"）
feishu-cli dept children <department_id> [--department-id-type open_department_id]
```

**权限要求**：`contact:user.base:readonly`（用户信息）、`contact:department.base:readonly`（部门查询）

---

## 通用注意事项

### 权限要求汇总

| 模块 | 权限 |
|------|------|
| 电子表格 | `sheets:spreadsheet` |
| 日历 | `calendar:calendar:readonly`、`calendar:calendar` |
| 任务 | `task:task:read`、`task:task:write`、`task:tasklist:read`、`task:tasklist:write` |
| 群聊 | `im:chat`、`im:chat:readonly`、`im:chat:member` |
| 画板 | `board:board` |
| 文件 | `drive:drive`、`drive:drive:readonly` |
| 素材 | `drive:drive`、`drive:drive:readonly` |
| 评论 | `drive:drive.comment:readonly`、`drive:drive.comment:write` |
| 知识库 | `wiki:wiki:readonly`、`wiki:wiki` |
| 搜索 | 需要 User Access Token |
| 用户/部门 | `contact:user.base:readonly`、`contact:department.base:readonly` |

### 错误处理

| 错误 | 原因 | 解决 |
|------|------|------|
| `rate limit exceeded` / 429 | API 频率限制 | 等待几秒后重试 |
| `no permission` | 应用权限不足 | 检查应用权限配置 |
| `invalid parameter` | 参数格式错误 | 检查参数类型和格式 |
| `not found` | 资源不存在 | 检查 ID/Token 是否正确 |
