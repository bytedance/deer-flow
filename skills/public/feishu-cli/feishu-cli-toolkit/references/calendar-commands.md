# 日历和日程详细参考

## 时间格式

所有时间参数统一使用 **RFC3339** 格式：`2024-01-21T14:00:00+08:00`

## 日历操作

### 列出日历

```bash
feishu-cli calendar list [--page-size 20]
```

### 获取日历详情

```bash
feishu-cli calendar get <calendar_id> [-o json]
```

### 获取主日历

```bash
feishu-cli calendar primary [-o json]
```

## 日程 CRUD

### 创建日程

```bash
feishu-cli calendar create-event \
  --calendar-id <id> \
  --summary "会议标题" \
  --start "2024-01-21T14:00:00+08:00" \
  --end "2024-01-21T15:00:00+08:00" \
  [--description "会议描述"] \
  [--location "会议室名称"]
```

必填参数：`--calendar-id`、`--summary`、`--start`、`--end`

### 列出日程

```bash
feishu-cli calendar list-events \
  --calendar-id <id> \
  [--start "2024-01-01T00:00:00+08:00"] \
  [--end "2024-01-31T23:59:59+08:00"] \
  [--page-size 50] \
  [--page-token <token>]
```

### 获取日程详情

```bash
feishu-cli calendar get-event --calendar-id <id> --event-id <event_id>
```

### 更新日程

```bash
feishu-cli calendar update-event \
  --calendar-id <id> \
  --event-id <event_id> \
  [--summary "新标题"] \
  [--start "2024-01-21T15:00:00+08:00"] \
  [--end "2024-01-21T16:00:00+08:00"] \
  [--description "新描述"] \
  [--location "新地点"]
```

### 删除日程

```bash
feishu-cli calendar delete-event --calendar-id <id> --event-id <event_id>
```

## 搜索日程

```bash
feishu-cli calendar event-search \
  --calendar-id <id> \
  --query "关键词" \
  [--start "2024-01-01T00:00:00+08:00"] \
  [--end "2024-12-31T23:59:59+08:00"] \
  [--page-size 20]
```

## 回复日程邀请

```bash
feishu-cli calendar event-reply <calendar_id> <event_id> --status <accept|decline|tentative>
```

| 状态 | 说明 |
|------|------|
| `accept` | 接受 |
| `decline` | 拒绝 |
| `tentative` | 暂定 |

## 参与人管理

### 添加参与人

```bash
feishu-cli calendar attendee add <calendar_id> <event_id> \
  [--user-ids id1,id2] \
  [--chat-ids oc_xxx]
```

至少需要指定 `--user-ids` 或 `--chat-ids` 之一。

### 列出参与人

```bash
feishu-cli calendar attendee list <calendar_id> <event_id> \
  [--page-size 50]
```

## 忙闲查询

```bash
feishu-cli calendar freebusy \
  --start "2024-01-01T00:00:00+08:00" \
  --end "2024-01-02T00:00:00+08:00" \
  --user-id <user_id>
```

## 命令别名

`calendar` 命令支持别名 `cal`：

```bash
feishu-cli cal list
feishu-cli cal primary
```

## 权限要求

| 权限 | 说明 |
|------|------|
| `calendar:calendar:readonly` | 读取日历和日程 |
| `calendar:calendar` | 创建/修改/删除日程（需单独申请） |
