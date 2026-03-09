---
name: feishu-cli-perm
description: >-
  飞书云文档权限管理。支持添加/删除/查看协作者、公开权限管理、分享密码、批量添加、
  权限检查、转移所有权。当用户请求"添加权限"、"权限管理"、"共享文档"、"授权"、
  "协作者"、"full_access"、"转移所有权"时使用。
argument-hint: <doc_token> --perm <view|edit|full_access>
user-invocable: true
allowed-tools: Bash, Read
---

# 飞书权限管理技能

飞书云文档权限管理：添加/删除/查看协作者、公开权限管理、分享密码、批量添加、权限检查、转移所有权。

## 适用场景

- 给飞书文档添加/删除协作者权限
- 查看文档协作者列表
- 管理文档公开权限（外部访问、链接分享）
- 设置/删除/更新分享密码
- 批量添加协作者
- 检查用户对文档的权限
- 转移文档所有权

## 命令格式

### 添加权限

```bash
feishu-cli perm add <TOKEN> \
  --doc-type <DOC_TYPE> \
  --member-type <MEMBER_TYPE> \
  --member-id <MEMBER_ID> \
  --perm <PERM> \
  [--notification]
```

### 更新权限

```bash
feishu-cli perm update <TOKEN> \
  --doc-type <DOC_TYPE> \
  --member-type <MEMBER_TYPE> \
  --member-id <MEMBER_ID> \
  --perm <PERM>
```

### 查看协作者列表

```bash
feishu-cli perm list <TOKEN> --doc-type <DOC_TYPE>
```

### 删除协作者

```bash
feishu-cli perm delete <TOKEN> \
  --doc-type <DOC_TYPE> \
  --member-type <MEMBER_TYPE> \
  --member-id <MEMBER_ID>
```

### 查看公开权限

```bash
feishu-cli perm public-get <TOKEN>
```

### 更新公开权限

```bash
feishu-cli perm public-update <TOKEN> \
  [--external-access] \
  [--link-share-entity <anyone_readable|anyone_editable|...>]
```

### 分享密码管理

```bash
# 创建分享密码
feishu-cli perm password create <TOKEN>

# 删除分享密码
feishu-cli perm password delete <TOKEN>

# 更新分享密码
feishu-cli perm password update <TOKEN>
```

### 批量添加协作者

```bash
feishu-cli perm batch-add <TOKEN> \
  --members-file <members.json> \
  [--notification]
```

### 权限检查

```bash
feishu-cli perm auth <TOKEN> --action <view|edit|...>
```

### 转移所有权

```bash
feishu-cli perm transfer-owner <TOKEN> \
  --member-type <MEMBER_TYPE> \
  --member-id <MEMBER_ID>
```

## 参数说明

### doc-type（云文档类型）

| 值 | 说明 |
|----|------|
| docx | 新版文档 |
| doc | 旧版文档 |
| sheet | 电子表格 |
| bitable | 多维表格 |
| wiki | 知识库 |
| file | 文件 |
| folder | 文件夹 |
| mindnote | 思维笔记 |
| minutes | 妙记 |
| slides | 幻灯片 |

### member-type（协作者 ID 类型）

| 值 | 说明 | 示例 |
|----|------|------|
| email | 邮箱 | user@example.com |
| openid | Open ID | ou_xxx |
| unionid | Union ID | on_xxx |
| userid | User ID | 123456 |
| openchat | 群聊 ID | oc_xxx |
| opendepartmentid | 部门 ID | od_xxx |
| groupid | 群组 ID | gc_xxx |
| wikispaceid | 知识空间 ID | ws_xxx |

### perm（权限角色）

| 值 | 说明 |
|----|------|
| view | 查看权限 |
| edit | 编辑权限 |
| full_access | 完全访问权限（可管理） |

### 可选参数

- `--notification`：添加权限后通知对方

## 示例

### 按邮箱添加用户为编辑者

```bash
feishu-cli perm add docx_xxxxxx \
  --doc-type docx \
  --member-type email \
  --member-id user@example.com \
  --perm edit \
  --notification
```

### 按 Open ID 添加用户查看权限

```bash
feishu-cli perm add docx_xxxxxx \
  --doc-type docx \
  --member-type openid \
  --member-id ou_xxxxxx \
  --perm view
```

### 给群聊添加编辑权限

```bash
feishu-cli perm add sht_xxxxxx \
  --doc-type sheet \
  --member-type openchat \
  --member-id oc_xxxxxx \
  --perm edit
```

### 按部门添加查看权限

```bash
feishu-cli perm add sht_xxxxxx \
  --doc-type sheet \
  --member-type opendepartmentid \
  --member-id od_xxxxxx \
  --perm view
```

### 更新已有权限

```bash
feishu-cli perm update docx_xxxxxx \
  --doc-type docx \
  --member-type email \
  --member-id user@example.com \
  --perm full_access
```

### 查看协作者列表

```bash
feishu-cli perm list docx_xxxxxx --doc-type docx
```

### 删除协作者

```bash
feishu-cli perm delete docx_xxxxxx \
  --doc-type docx \
  --member-type email \
  --member-id user@example.com
```

### 查看公开权限设置

```bash
feishu-cli perm public-get docx_xxxxxx
```

### 更新公开权限

```bash
feishu-cli perm public-update docx_xxxxxx \
  --external-access \
  --link-share-entity anyone_readable
```

### 创建分享密码

```bash
feishu-cli perm password create docx_xxxxxx
```

### 删除分享密码

```bash
feishu-cli perm password delete docx_xxxxxx
```

### 批量添加协作者

```bash
feishu-cli perm batch-add docx_xxxxxx \
  --members-file members.json \
  --notification
```

members.json 格式示例：
```json
[
  {"member_type": "email", "member_id": "user1@example.com", "perm": "edit"},
  {"member_type": "email", "member_id": "user2@example.com", "perm": "view"}
]
```

### 权限检查

```bash
feishu-cli perm auth docx_xxxxxx --action view
```

### 转移所有权

```bash
feishu-cli perm transfer-owner docx_xxxxxx \
  --member-type email \
  --member-id user@example.com
```

## 执行流程

1. **收集文档信息**
   - 获取文档 Token（从 URL 或用户提供）
   - 确定 doc-type（根据 Token 前缀判断）

2. **收集协作者信息**
   - 确定 member-type（邮箱最常用）
   - 获取 member-id

3. **选择权限级别**
   - view：仅查看
   - edit：可编辑
   - full_access：完全访问

4. **执行命令**
   - 可选添加 `--notification` 通知对方

## Token 前缀对应关系

| 前缀 | doc-type |
|------|----------|
| docx_ | docx |
| doccn | doc |
| sht_ | sheet |
| bascn | bitable |
| wikicn | wiki |
| fldcn | folder |

## 常见默认操作

**创建文档后自动授权**：

```bash
# 创建文档后，给指定用户添加完全访问权限
feishu-cli perm add <doc_token> \
  --doc-type docx \
  --member-type email \
  --member-id user@example.com \
  --perm full_access \
  --notification
```

