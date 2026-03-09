# feishu-cli perm add 参考

## 命令概要

```bash
feishu-cli perm add <TOKEN> \
  --doc-type <DOC_TYPE> \
  --member-type <MEMBER_TYPE> \
  --member-id <MEMBER_ID> \
  --perm <PERM> \
  [--notification]
```

## 参数枚举

### doc-type（云文档类型）

- doc、sheet、file、wiki、bitable、docx、folder、mindnote、minutes、slides

### member-type（协作者 ID 类型）

- email、openid、unionid、openchat、opendepartmentid、userid、groupid、wikispaceid

### perm（权限角色）

- view、edit、full_access

### notification

- 添加权限后是否通知对方，传入即生效

## 输入检查清单

- TOKEN 与 doc-type 是否匹配（例如 docx_xxx 用 docx）
- member-type 与 member-id 是否一致（例如 openid + ou_xxx）
- 是否需要通知对方（--notification）

## 示例

**按 email 添加用户为可编辑协作者：**

```bash
feishu-cli perm add docx_xxxxxx \
  --doc-type docx \
  --member-type email \
  --member-id user@example.com \
  --perm edit
```

**按部门 ID 添加查看权限：**

```bash
feishu-cli perm add sht_xxxxxx \
  --doc-type sheet \
  --member-type opendepartmentid \
  --member-id od_xxxxxx \
  --perm view
```

**给群聊添加编辑权限并通知：**

```bash
feishu-cli perm add docx_xxxxxx \
  --doc-type docx \
  --member-type openchat \
  --member-id oc_xxxxxx \
  --perm edit \
  --notification
```
