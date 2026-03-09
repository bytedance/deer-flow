# 搜索命令详细参考

**重要**：搜索 API 需要 **User Access Token**，不能使用 App Access Token。

## User Access Token 获取方式

1. **命令行参数**：`--user-access-token <token>`
2. **环境变量**：`FEISHU_USER_ACCESS_TOKEN=<token>`

Token 有效期约 2 小时，Refresh Token 有效期 30 天。

## 搜索消息

```bash
feishu-cli search messages "关键词" \
  --user-access-token <token> \
  [--chat-ids oc_xxx,oc_yyy] \
  [--from-ids ou_xxx] \
  [--at-chatter-ids ou_xxx] \
  [--message-type file|image|media] \
  [--chat-type group_chat|p2p_chat] \
  [--from-type bot|user] \
  [--start-time 1704067200] \
  [--end-time 1704153600] \
  [--page-size 20] \
  [--page-token <token>]
```

### 筛选参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `--chat-ids` | string | 限定群聊范围（逗号分隔） |
| `--from-ids` | string | 限定发送者（逗号分隔） |
| `--at-chatter-ids` | string | 限定被@的用户（逗号分隔） |
| `--message-type` | string | 消息类型：`file`/`image`/`media` |
| `--chat-type` | string | 会话类型：`group_chat`（群聊）/`p2p_chat`（单聊） |
| `--from-type` | string | 发送者类型：`bot`（机器人）/`user`（用户） |
| `--start-time` | string | 起始时间（Unix 秒级时间戳） |
| `--end-time` | string | 结束时间（Unix 秒级时间戳） |

### 示例

```bash
# 搜索特定群里的文件消息
feishu-cli search messages "周报" \
  --user-access-token u-xxx \
  --chat-ids oc_xxx \
  --message-type file

# 搜索某时间段内的消息
feishu-cli search messages "上线" \
  --user-access-token u-xxx \
  --start-time 1704067200 \
  --end-time 1704153600

# 搜索机器人发送的消息
feishu-cli search messages "告警" \
  --user-access-token u-xxx \
  --from-type bot
```

## 搜索应用

```bash
feishu-cli search apps "应用名称" \
  --user-access-token <token> \
  [--page-size 20] \
  [--page-token <token>]
```
