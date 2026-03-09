---
name: feishu-cli-msg
description: >-
  飞书消息全功能管理。发送消息（text/post/interactive 卡片等 11 种类型）、回复消息、
  转发/合并转发、Reaction 表情回应、Pin 置顶消息、删除消息、消息详情、会话历史、
  搜索群聊。当用户请求"发消息"、"回复"、"转发"、"置顶"、"Reaction"、"表情回应"、
  "消息历史"、"Pin 消息"时使用。
argument-hint: <receive_id> [--msg-type <type>]
user-invocable: true
allowed-tools: Bash, Read, Write
---

# 飞书消息发送技能

通过 feishu-cli 发送飞书消息，支持多种消息类型和丰富的消息管理操作。

## 核心概念

### 消息架构

飞书消息 API 的 `content` 字段是一个 **JSON 字符串**（不是 JSON 对象）。CLI 提供三种输入方式：

| 输入方式 | 参数 | 适用场景 |
|---------|------|---------|
| 快捷文本 | `--text "内容"` | 纯文本消息，最简单 |
| 内联 JSON | `--content '{"key":"val"}'` 或 `-c` | 简单 JSON，一行搞定 |
| JSON 文件 | `--content-file file.json` | 复杂消息（卡片、富文本等） |

**优先级**：`--text` > `--content` > `--content-file`（同时指定时前者优先）

### 接收者类型

| --receive-id-type | 说明 | 示例 |
|-------------------|------|------|
| email | 邮箱地址 | user@example.com |
| open_id | Open ID | ou_xxx |
| user_id | User ID | xxx |
| union_id | Union ID | on_xxx |
| chat_id | 群聊 ID | oc_xxx |

## 消息类型选择

### 决策树（Claude 未指定类型时自动选择）

**默认优先使用 `interactive`（卡片消息）**，样式美观、内容丰富、支持颜色/多列/按钮等。

```
用户需求
├─ 【默认】通知/报告/告警/任何有信息量的消息 → interactive（卡片）
├─ 发送已上传的图片/文件/音视频 → image/file/audio/media
├─ 分享群聊或用户名片 → share_chat/share_user
├─ 会话分割线（仅 p2p） → system
└─ 仅以下场景才用 text/post：
   ├─ 用户明确要求发纯文本 → text
   └─ 用户明确要求发富文本 → post
```

**为什么优先卡片**：text 不支持任何格式渲染，post 样式有限，卡片支持彩色 header、多列 fields、按钮、分割线、备注等，视觉效果远优于其他类型。

### 消息类型一览

| 类型 | 说明 | content 格式 | 大小限制 |
|------|------|-------------|---------|
| text | 纯文本 | `{"text":"内容"}` | 150 KB |
| post | 富文本 | `{"zh_cn":{"title":"","content":[[...]]}}` | 150 KB |
| image | 图片 | `{"image_key":"img_xxx"}` | — |
| file | 文件 | `{"file_key":"file_v2_xxx"}` | — |
| audio | 语音 | `{"file_key":"file_v2_xxx"}` | — |
| media | 视频 | `{"file_key":"...","image_key":"..."}` | — |
| sticker | 表情包 | `{"file_key":"file_v2_xxx"}` | 仅转发 |
| interactive | 卡片 | Card JSON / template_id / card_id | 30 KB |
| share_chat | 群名片 | `{"chat_id":"oc_xxx"}` | — |
| share_user | 个人名片 | `{"user_id":"ou_xxx"}` | — |
| system | 系统分割线 | `{"type":"divider",...}` | 仅 p2p |

## 发送命令

### 基础格式

```bash
feishu-cli msg send \
  --receive-id-type <type> \
  --receive-id <id> \
  [--msg-type <msg_type>] \
  [--text "<text>" | --content '<json>' | --content-file <file.json>]
```

### text 类型

```bash
# 最简形式（默认 msg-type 为 text）
feishu-cli msg send \
  --receive-id-type email \
  --receive-id user@example.com \
  --text "你好，这是一条测试消息"
```

text 类型支持的内联语法：
- `@` 用户：`<at user_id="ou_xxx">Tom</at>`
- `@` 所有人：`<at user_id="all"></at>`

**注意**：text 类型**不支持**富文本样式（加粗、斜体、下划线、删除线、超链接等均不会渲染）。如需格式排版，请使用 `post` 类型。

### post 类型（富文本）

推荐使用 `md` 标签承载 Markdown，一个 `md` 标签独占一个段落：

```bash
cat > /tmp/msg.json << 'EOF'
{
  "zh_cn": {
    "title": "项目进展通知",
    "content": [
      [{"tag": "md", "text": "**本周进展**\n- 完成功能 A 开发\n- 修复 3 个 Bug\n- [查看详情](https://example.com)"}],
      [{"tag": "md", "text": "**下周计划**\n1. 功能 B 开发\n2. 性能优化"}]
    ]
  }
}
EOF

feishu-cli msg send \
  --receive-id-type email \
  --receive-id user@example.com \
  --msg-type post \
  --content-file /tmp/msg.json
```

post 支持的 tag 类型：

| tag | 说明 | 主要属性 |
|-----|------|---------|
| text | 文本 | text, style（bold/italic/underline/lineThrough） |
| a | 超链接 | text, href |
| at | @用户 | user_id, user_name |
| img | 图片 | image_key, width, height |
| media | 视频 | file_key, image_key |
| emotion | 表情 | emoji_type |
| hr | 分割线 | — |
| code_block | 代码块 | language, text |
| md | Markdown | text（独占段落，推荐使用） |

### interactive 类型（卡片消息）

卡片消息有三种发送方式：

**方式一：完整 Card JSON（推荐，最灵活）**

```bash
cat > /tmp/card.json << 'EOF'
{
  "header": {
    "template": "blue",
    "title": {"tag": "plain_text", "content": "任务完成通知"}
  },
  "elements": [
    {"tag": "markdown", "content": "**项目**: feishu-cli\n**状态**: 已完成\n**负责人**: <at id=all></at>"},
    {"tag": "hr"},
    {"tag": "note", "elements": [{"tag": "plain_text", "content": "由 CI/CD 自动发送"}]}
  ]
}
EOF

feishu-cli msg send \
  --receive-id-type email \
  --receive-id user@example.com \
  --msg-type interactive \
  --content-file /tmp/card.json
```

**方式二：template_id**

```bash
cat > /tmp/card.json << 'EOF'
{
  "type": "template",
  "data": {
    "template_id": "AAqk1xxxxxx",
    "template_variable": {"name": "张三", "status": "已完成"}
  }
}
EOF

feishu-cli msg send \
  --receive-id-type email \
  --receive-id user@example.com \
  --msg-type interactive \
  --content-file /tmp/card.json
```

**方式三：card_id**

```bash
feishu-cli msg send \
  --receive-id-type email \
  --receive-id user@example.com \
  --msg-type interactive \
  --content '{"type":"card","data":{"card_id":"7371713483664506900"}}'
```

#### Card JSON 结构（v1 vs v2）

**v1 格式（推荐，兼容性好）**：

```json
{
  "header": {"template": "blue", "title": {"tag": "plain_text", "content": "标题"}},
  "elements": [...]
}
```

**v2 格式（更多组件）**：

```json
{
  "schema": "2.0",
  "header": {"template": "blue", "title": {"tag": "plain_text", "content": "标题"}},
  "body": {"direction": "vertical", "elements": [...]}
}
```

v2 额外支持：table（表格）、chart（图表）、form_container（表单）、column_set（多列布局）等高级组件。对于简单通知，v1 足够；需要复杂布局时用 v2。

#### header 颜色模板

| 颜色值 | 色系 | 推荐场景 |
|--------|------|---------|
| blue | 蓝色 | 通用通知、信息 |
| wathet | 浅蓝 | 轻量提示 |
| turquoise | 青色 | 进行中状态 |
| green | 绿色 | 成功、完成 |
| yellow | 黄色 | 注意、提醒 |
| orange | 橙色 | 警告 |
| red | 红色 | 错误、紧急 |
| carmine | 深红 | 严重告警 |
| violet | 紫罗兰 | 特殊标记 |
| purple | 紫色 | 自定义分类 |
| indigo | 靛蓝 | 深色主题 |
| grey | 灰色 | 已处理、归档 |

**语义化推荐**：绿=成功 / 蓝=通知 / 橙=警告 / 红=错误 / 灰=已处理

#### 常用组件速查

**内容组件**：

| 组件 | tag | 说明 |
|------|-----|------|
| Markdown | `markdown` | 支持 lark_md 语法，最常用 |
| 分割线 | `hr` | 水平分割线 |
| 备注 | `note` | 底部灰色小字备注 |
| 图片 | `img` | 图片展示 |

**布局组件**：

| 组件 | tag | 说明 |
|------|-----|------|
| 文本+附加 | `div` | 文本块，可含 fields（多列）和 extra（右侧附加） |
| 多列布局 | `column_set`（v2） | 横向分栏布局 |

**交互组件**：

| 组件 | tag | 说明 |
|------|-----|------|
| 按钮 | `button` | default/primary/danger 三种类型 |
| 下拉选择 | `select_static` | 静态下拉菜单 |
| 日期选择 | `date_picker` | 日期选择器 |
| 折叠菜单 | `overflow` | 更多操作菜单 |

#### 卡片 Markdown 语法（lark_md）

卡片内 `markdown` 组件使用 `lark_md` 语法，与标准 Markdown 有差异：

```markdown
# 支持的语法
**加粗** *斜体* ~~删除线~~ [链接](url) `行内代码`
![图片](img_v2_xxx)

# 特有语法
<font color='green'>绿色文字</font>
<font color='red'>红色文字</font>
<font color='grey'>灰色文字</font>
<at id=ou_xxx></at>
<at id=all></at>
```

**注意**：lark_md 的 `<font color>` 仅支持 green/red/grey 三种颜色。

### 常用卡片模板

#### 模板 1：简单通知卡片

```json
{
  "header": {
    "template": "blue",
    "title": {"tag": "plain_text", "content": "通知标题"}
  },
  "elements": [
    {"tag": "markdown", "content": "通知内容，支持 **加粗** 和 [链接](https://example.com)"},
    {"tag": "note", "elements": [{"tag": "plain_text", "content": "来自自动化工具"}]}
  ]
}
```

#### 模板 2：告警卡片（多列 + 按钮）

```json
{
  "header": {
    "template": "red",
    "title": {"tag": "plain_text", "content": "告警通知"}
  },
  "elements": [
    {
      "tag": "div",
      "fields": [
        {"is_short": true, "text": {"tag": "lark_md", "content": "**服务**\napi-gateway"}},
        {"is_short": true, "text": {"tag": "lark_md", "content": "**级别**\n<font color='red'>P0</font>"}},
        {"is_short": true, "text": {"tag": "lark_md", "content": "**时间**\n2024-01-01 10:00"}},
        {"is_short": true, "text": {"tag": "lark_md", "content": "**影响**\n<font color='red'>用户无法登录</font>"}}
      ]
    },
    {"tag": "hr"},
    {
      "tag": "action",
      "actions": [
        {"tag": "button", "text": {"tag": "plain_text", "content": "查看详情"}, "type": "primary", "url": "https://example.com/alert/123"},
        {"tag": "button", "text": {"tag": "plain_text", "content": "忽略"}, "type": "default"}
      ]
    }
  ]
}
```

#### 模板 3：进度报告卡片

```json
{
  "header": {
    "template": "green",
    "title": {"tag": "plain_text", "content": "构建报告"}
  },
  "elements": [
    {"tag": "markdown", "content": "**项目**: feishu-cli\n**分支**: main\n**提交**: abc1234"},
    {"tag": "hr"},
    {"tag": "markdown", "content": "<font color='green'>Tests: 42/42 passed</font>\n<font color='green'>Build: Success</font>\n<font color='grey'>Duration: 3m 25s</font>"},
    {"tag": "hr"},
    {
      "tag": "action",
      "actions": [
        {"tag": "button", "text": {"tag": "plain_text", "content": "查看日志"}, "type": "default", "url": "https://ci.example.com/build/123"}
      ]
    },
    {"tag": "note", "elements": [{"tag": "plain_text", "content": "CI/CD Pipeline #123"}]}
  ]
}
```

#### 模板 4：文档操作通知

```json
{
  "header": {
    "template": "turquoise",
    "title": {"tag": "plain_text", "content": "文档操作通知"}
  },
  "elements": [
    {
      "tag": "div",
      "fields": [
        {"is_short": true, "text": {"tag": "lark_md", "content": "**操作类型**\n创建文档"}},
        {"is_short": true, "text": {"tag": "lark_md", "content": "**状态**\n<font color='green'>成功</font>"}}
      ]
    },
    {"tag": "markdown", "content": "**文档标题**: 周报 2024-W01\n**文档链接**: [点击查看](https://xxx.feishu.cn/docx/abc123)"},
    {"tag": "note", "elements": [{"tag": "plain_text", "content": "由 feishu-cli 自动创建"}]}
  ]
}
```

#### 模板 5：审批确认卡片（多按钮）

```json
{
  "header": {
    "template": "orange",
    "title": {"tag": "plain_text", "content": "审批请求"}
  },
  "elements": [
    {"tag": "markdown", "content": "**申请人**: 张三\n**申请类型**: 服务器扩容\n**说明**: 线上流量增长，需要增加 2 台服务器"},
    {"tag": "hr"},
    {
      "tag": "action",
      "actions": [
        {"tag": "button", "text": {"tag": "plain_text", "content": "批准"}, "type": "primary"},
        {"tag": "button", "text": {"tag": "plain_text", "content": "拒绝"}, "type": "danger"},
        {"tag": "button", "text": {"tag": "plain_text", "content": "查看详情"}, "type": "default", "url": "https://example.com/approval/456"}
      ]
    }
  ]
}
```

## 回复消息

回复指定消息，支持与 `msg send` 相同的消息类型和输入方式。

```bash
# 文本回复
feishu-cli msg reply <message_id> --text "收到，我来处理"

# 卡片回复
feishu-cli msg reply <message_id> --msg-type interactive --content-file /tmp/card.json

# 富文本回复
feishu-cli msg reply <message_id> --msg-type post --content-file /tmp/post.json
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--msg-type` | 消息类型 | `text` |
| `--text` / `--content` / `--content-file` | 消息内容（三选一） | 必填 |

## 合并转发

将多条消息合并转发给指定接收者。

```bash
feishu-cli msg merge-forward \
  --receive-id user@example.com \
  --receive-id-type email \
  --message-ids om_xxx,om_yyy,om_zzz
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--receive-id` | 接收者 ID | 必填 |
| `--receive-id-type` | 接收者类型 | `email` |
| `--message-ids` | 消息 ID 列表（逗号分隔） | 必填 |

## Reaction 表情回应

给消息添加/删除/查询表情回应。

```bash
# 添加表情
feishu-cli msg reaction add <message_id> --emoji-type THUMBSUP

# 删除表情
feishu-cli msg reaction remove <message_id> --reaction-id <REACTION_ID>

# 查询表情列表
feishu-cli msg reaction list <message_id> [--emoji-type THUMBSUP] [--page-size 20]
```

常用 emoji-type：`THUMBSUP`（点赞）、`SMILE`（微笑）、`LAUGH`（大笑）、`HEART`（爱心）、`JIAYI`（加一）、`OK`、`FIRE`

## Pin 置顶消息

```bash
# 置顶消息
feishu-cli msg pin <message_id>

# 取消置顶
feishu-cli msg unpin <message_id>

# 获取群内置顶消息列表
feishu-cli msg pins --chat-id <chat_id> [--start-time <ms_timestamp>] [--end-time <ms_timestamp>]
```

`--start-time` 和 `--end-time` 使用**毫秒级**时间戳。

## 其他消息命令

### 获取消息详情

```bash
feishu-cli msg get <message_id>
feishu-cli msg get om_xxx --output json
```

### 转发消息

```bash
feishu-cli msg forward <message_id> \
  --receive-id user@example.com \
  --receive-id-type email
```

### 删除消息

仅能删除机器人自己发送的消息，不可恢复。

```bash
feishu-cli msg delete <message_id>
```

### 获取消息列表

```bash
feishu-cli msg list \
  --container-id oc_xxx \
  --container-id-type chat \
  --page-size 20 \
  --sort-type ByCreateTimeDesc
```

支持参数：`--start-time`、`--end-time`（秒级时间戳）、`--page-token`。

### 获取会话历史

```bash
feishu-cli msg history \
  --container-id oc_xxx \
  --container-id-type chat \
  --sort-type ByCreateTimeAsc \
  --page-size 50
```

### 查询消息已读用户

```bash
feishu-cli msg read-users <message_id>
feishu-cli msg read-users om_xxx --user-id-type user_id --page-size 50
```

### 搜索群聊

```bash
feishu-cli msg search-chats --query "项目群"
feishu-cli msg search-chats --page-size 20
```

### 搜索消息（需 User Access Token）

```bash
feishu-cli search messages "关键词" \
  --user-access-token u-xxx \
  --chat-ids oc_xxx \
  --message-type file \
  --start-time 1704067200
```

## 执行流程

Claude 发送消息时按以下流程操作：

1. **确定接收者**：默认 `user@example.com`（email），或从上下文获取
2. **选择消息类型**：
   - 用户明确指定类型 → 使用指定类型
   - **默认使用 `interactive`（卡片消息）** → 根据内容语义选择 header 颜色和合适的组件布局
   - 仅在用户明确要求纯文本/富文本时 → 使用 `text` / `post`
3. **构造卡片内容**：
   - 根据消息语义选择 header 颜色（绿=成功、红=错误、橙=警告、蓝=通知、灰=归档）
   - 使用 `markdown` 组件承载主要内容
   - 有多个键值对时使用 `div` + `fields` 多列布局
   - 需要操作链接时添加 `action` + `button`
   - 底部添加 `note` 备注来源
   - 将 JSON 写入临时文件后用 `--content-file` 发送
4. **发送并检查结果**：执行命令，确认返回 message_id

## 权限要求

| 权限 | 说明 |
|------|------|
| `im:message` | 消息读写 |
| `im:message:send_as_bot` | 以机器人身份发送消息 |
| `im:chat:readonly` | 搜索群聊 |
| `im:message:readonly` | 获取历史消息 |

## 注意事项

| 限制 | 说明 |
|------|------|
| text 大小限制 | 单条最大 150 KB |
| 卡片/富文本大小限制 | 单条最大 30 KB |
| system 消息 | 仅 p2p 会话有效，群聊无效 |
| sticker 消息 | 仅支持转发收到的表情包，不支持自行上传 |
| 卡片按钮回调 | 按钮的交互回调需应用服务端支持，CLI 发送的按钮仅 url 跳转有效 |
| API 频率限制 | 请求过快返回 429，等待几秒后重试 |
| 删除消息 | 仅能删除机器人发送的消息 |

## 错误处理

| 错误 | 原因 | 解决 |
|------|------|------|
| `content format of a post type is incorrect` | post 类型 JSON 格式错误 | 确保格式为 `{"zh_cn":{"title":"","content":[[...]]}}` |
| `invalid receive_id` | 接收者 ID 无效 | 检查 --receive-id-type 和 --receive-id 是否匹配 |
| `bot has no permission` | 机器人无权限 | 确认应用有 `im:message:send_as_bot` 权限 |
| `rate limit exceeded` | API 限流 | 等待几秒后重试 |
| `user not found` | 用户不存在 | 检查邮箱或 ID 是否正确 |
| `card content too large` | 卡片 JSON 超过 30 KB | 精简卡片内容或拆分为多条消息 |

## 参考文档

- `references/message_content.md`：各消息类型的 content JSON 结构详解
- `references/card_schema.md`：卡片消息完整构造指南（组件、布局、模板）
