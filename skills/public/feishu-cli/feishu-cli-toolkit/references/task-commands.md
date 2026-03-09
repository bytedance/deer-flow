# 任务管理详细参考

飞书任务 V2 API。任务 ID 为 UUID 格式（如 `d300a75f-c56a-4be9-80d6-e47653f6xxxx`）。

## 任务 CRUD

### 创建任务

```bash
feishu-cli task create \
  --summary "任务标题" \
  [--description "详细描述"] \
  [--due "2024-02-01"] \
  [--origin-href "https://example.com"] \
  [--origin-platform "feishu-cli"]
```

截止时间格式：`YYYY-MM-DD HH:mm:ss` 或 `YYYY-MM-DD`

### 列出任务

```bash
feishu-cli task list [--completed | --uncompleted] [--page-size 20] [--page-token <token>]
```

### 获取任务详情

```bash
feishu-cli task get <task_id> [-o json]
```

### 更新任务

```bash
feishu-cli task update <task_id> \
  [--summary "新标题"] \
  [--description "新描述"] \
  [--due "2024-03-01"]
```

### 完成任务

```bash
feishu-cli task complete <task_id>
```

### 删除任务

```bash
feishu-cli task delete <task_id>
```

## 子任务管理

### 创建子任务

```bash
feishu-cli task subtask create <task_guid> --summary "子任务标题" [-o json]
```

### 列出子任务

```bash
feishu-cli task subtask list <task_guid> [--page-size 20] [--page-token <token>] [-o json]
```

## 成员管理

### 添加成员

```bash
feishu-cli task member add <task_guid> --members id1,id2 --role assignee
```

| 角色 | 说明 |
|------|------|
| `assignee` | 执行者（默认） |
| `follower` | 关注者 |

### 移除成员

```bash
feishu-cli task member remove <task_guid> --members id1,id2 --role assignee
```

## 提醒管理

### 添加提醒

```bash
feishu-cli task reminder add <task_guid> --minutes 30
```

`--minutes`：提前提醒的分钟数，`0` 表示在截止时间提醒。

### 移除提醒

```bash
feishu-cli task reminder remove <task_guid> --ids id1,id2
```

## 任务清单

任务清单是任务的分组容器，一个任务可以属于多个清单。

### 创建清单

```bash
feishu-cli tasklist create --name "Sprint 计划" [-o json]
```

### 列出清单

```bash
feishu-cli tasklist list [--page-size 20] [--page-token <token>] [-o json]
```

### 获取清单详情

```bash
feishu-cli tasklist get <tasklist_guid> [-o json]
```

### 删除清单

```bash
feishu-cli tasklist delete <tasklist_guid>
```

## 权限要求

| 权限 | 说明 |
|------|------|
| `task:task:read` | 读取任务（需单独申请） |
| `task:task:write` | 创建/修改/删除任务（需单独申请） |
| `task:tasklist:read` | 读取任务清单 |
| `task:tasklist:write` | 管理任务清单 |
