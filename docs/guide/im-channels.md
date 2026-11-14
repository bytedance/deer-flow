# IM Channels

DeerFlow supports receiving tasks from messaging apps. Channels auto-start when configured — no public IP required for any of them.

Generated-file replies explain when a channel cannot send attachments. If some or all uploads fail, DeerFlow sends one combined notice naming the unsent files when the platform still accepts replies. Successful uploads add no duplicate confirmation. Files remain in the DeerFlow conversation; an expired reply window is logged without switching to proactive messaging.

Telegram retries photos rejected for invalid dimensions or image processing once as documents, preserving the original file and reply target.

Cancelling a channel restart discards its pending configuration reload, preserving newer runtime settings applied afterward.

Invalid UTF-8 in `channels/store.json` follows the same recovery policy as malformed JSON:
SQL migration warns and skips the file, leaving it unchanged so channels can start; the
memory backend's JSON store warns and starts empty, replacing the file on its next write.

On Windows, JSON runtime channel-config saves wait for a competing file-lock holder
without the operating system's roughly ten-second cutoff. A wait reaching 50 retries
(about ten seconds) logs the lock-file path once; permanent lock errors fail immediately.

Conversation-binding, runtime channel-credential and WeChat auth-state saves preserve the original
persistence failure when staged-file cleanup also fails. Remaining cleanup still runs, and warnings
identify copies that could not be removed. Buzz keeps failed snapshots available for retry, even if
cleanup or logging fails.

On startup, runtime credential and WeChat auth stores remove their own `.<state-file>.deerflow-*.tmp`
staging files older than 24 hours. Fresh files, symlinks and unrelated files are preserved. Older
anonymous `tmp*.tmp` files require manual inspection because their writer cannot be identified safely.

DeerFlow can also expose user-owned IM channel connections in the workspace UI. When `channel_connections` is enabled, logged-in users can bind Telegram, Slack, Discord, Feishu/Lark, DingTalk, WeChat, WeCom, QQ, or Buzz from the sidebar / Settings > Channels. It reuses the existing outbound `channels.*` transports, so no public IP or provider callback URL is required. Incoming IM messages then run under the connected DeerFlow user account. See [IM Channel Connections](../../backend/docs/IM_CHANNEL_CONNECTIONS.md) for setup and security notes. Buzz backlog paging stops with a warning if timestamp-based queries cannot advance, and channel removal closes both live and backlog subscriptions.

For Discord and Buzz, the local and Docker launchers detect the required optional
dependencies when both `channel_connections.enabled` and the corresponding
`channel_connections.<provider>.enabled` are `true`. Selecting Discord in
`make setup` sets these flags. A nonempty `UV_EXTRAS` overrides configuration
auto-detection, so include `discord` or `buzz` there if you set it manually.

| Channel | Transport | Difficulty |
|---------|-----------|------------|
| Telegram | Bot API (long-polling) | Easy |
| Slack | Socket Mode | Moderate |
| Feishu / Lark | WebSocket | Moderate |
| WeChat | Tencent iLink (long-polling) | Moderate |
| WeCom | WebSocket | Moderate |
| QQ | WebSocket (text-only C2C and group @mentions; four/five passive replies per source) | Moderate |
| DingTalk | Stream Push (WebSocket) | Moderate |
| Buzz | Nostr relay (WebSocket, NIP-42) | Moderate |

Attachments saved by the shared IM ingestion pipeline or Feishu/DingTalk's
embedded downloads keep distinct filenames, including when concurrent uploads
choose the same name. The final filename is passed to the agent and used for
sandbox sync; an existing conversation file is not overwritten.
Embedded client uploads also keep earlier same-name files under distinct names.
Renamed originals and Markdown companions retain private source snapshots and
become visible only after the complete copy is published.

Feishu and DingTalk attachment transfers return standalone temporary sandboxes
to the pool after synchronization, without interrupting an active run.

Feishu desktop posts can include a caption and files. Commands use the caption,
and a command that starts a chat turn, such as `/goal <condition>`, passes the
files to that turn.

**Configuration in `config.yaml`:**

Discord's `channels.discord.allowed_guilds` accepts one positive numeric guild
ID (quoted or unquoted) or a YAML list. Unset, `null`, `[]`, or a blank string
allows all guilds. Invalid entries are ignored with a warning; any other
configured value yielding no valid ID denies every guild and logs an error.
`allowed_channels` accepts one channel ID (quoted or unquoted) or a YAML list
of IDs exempt from `mention_only`, within allowed guilds. An empty value gives
no exemptions, so `mention_only` applies everywhere when enabled.

Discord inbound attachments have a 25 MiB download limit. Oversized-file notices
show the enforced limit so senders can resize or compress the attachment.

```yaml
channels:
  # LangGraph-compatible Gateway API base URL (default: http://localhost:8001/api)
  langgraph_url: http://localhost:8001/api
  # Gateway API URL (default: http://localhost:8001)
  gateway_url: http://localhost:8001

  # Maximum queued or provider-reserved inbound messages (default: 1000)
  inbound_queue_maxsize: 1000
  # Fixed number of long-lived inbound handler workers (default: 5)
  max_concurrency: 5
  # Seconds to drain accepted work before cancelling active handlers (default: 3)
  shutdown_grace_period_seconds: 3

  # Optional: global session defaults for all mobile channels
  session:
    assistant_id: lead_agent  # or a custom agent name; custom agents are routed via lead_agent + agent_name
    context:
      thinking_enabled: true
      is_plan_mode: false
      subagent_enabled: false

  feishu:
    enabled: true
    app_id: $FEISHU_APP_ID
    app_secret: $FEISHU_APP_SECRET
    # domain: https://open.feishu.cn       # China (default)
    # domain: https://open.larksuite.com   # International

  qq:
    enabled: true
    app_id: $QQ_APP_ID
    client_secret: $QQ_CLIENT_SECRET
    allowed_users: []  # QQ OpenIDs, not QQ account numbers; empty allows all; one ID is one entry

  wecom:
    enabled: true
    bot_id: $WECOM_BOT_ID
    bot_secret: $WECOM_BOT_SECRET
    # Optional: extra host suffixes inbound media downloads may come from, in
    # addition to the built-in qq.com family and WeCom's official COS media
    # host (ww-aibot-img-1258476243.<region>.myqcloud.com); add one here if
    # WeCom rotates to a new COS account or media goes through a proxy
    allowed_media_hosts: []

  slack:
    enabled: true
    bot_token: $SLACK_BOT_TOKEN     # xoxb-...
    app_token: $SLACK_APP_TOKEN     # xapp-... (Socket Mode)
    allowed_users: []               # empty = allow all

  telegram:
    enabled: true
    bot_token: $TELEGRAM_BOT_TOKEN
    # Optional: render final Markdown replies as Telegram Rich Messages.
    rich_messages: false
    allowed_users: []               # numeric user IDs, not @usernames; empty = allow all

  wechat:
    enabled: false
    bot_token: $WECHAT_BOT_TOKEN
    ilink_bot_id: $WECHAT_ILINK_BOT_ID
    qrcode_login_enabled: true      # optional: allow first-time QR bootstrap when bot_token is absent
    allowed_users: []               # iLink user IDs; empty allows all; one ID is one entry
    polling_timeout: 35             # timing values must be positive finite seconds
    polling_retry_delay: 5
    qrcode_poll_interval: 2
    qrcode_poll_timeout: 180
    state_dir: ./.deer-flow/wechat/state
    max_inbound_image_bytes: 20971520
    max_outbound_image_bytes: 20971520
    max_inbound_file_bytes: 52428800
    max_outbound_file_bytes: 52428800
    # Inbound media downloads stream with the caps above and are restricted to
    # these host suffixes (plus *.qq.com and the cdn_base_url host by default)
    allowed_media_hosts: []

    # Optional: per-channel / per-user session settings
    session:
      assistant_id: mobile-agent  # custom agent names are also supported here
      context:
        thinking_enabled: false
      users:
        "123456789":
          assistant_id: vip-agent
          config:
            recursion_limit: 150
          context:
            thinking_enabled: true
            subagent_enabled: true

  dingtalk:
    enabled: true
    client_id: $DINGTALK_CLIENT_ID             # Client ID of your DingTalk application
    client_secret: $DINGTALK_CLIENT_SECRET     # Client Secret of your DingTalk application
    allowed_users: []                          # empty = allow all
    card_template_id: ""                       # Optional: AI Card template ID for streaming typewriter effect
```

Notes:
- `assistant_id: lead_agent` calls the default LangGraph assistant directly.
- If `assistant_id` is set to a custom agent name, DeerFlow still routes through `lead_agent` and injects that value as `agent_name`, so the custom agent's SOUL/config takes effect for IM channels.
- IM channel workers call Gateway's LangGraph-compatible API internally and automatically attach process-local internal auth plus the CSRF cookie/header pair required for thread and run creation.
- Inbound work is bounded to `inbound_queue_maxsize` pending messages plus `max_concurrency` active workers. When capacity is exhausted, socket/polling providers drop new messages before sending DeerFlow's working acknowledgment and emit a rate-limited warning. Buzz leaves its replay cursor unchanged and reconnects for relay replay; GitHub webhooks return `503`, marking the delivery failed for manual/API redelivery. Shutdown closes admission immediately, keeps channel transports available while accepted messages drain for up to `shutdown_grace_period_seconds`, then cancels and awaits active handlers before closing provider resources; the Gateway's outer timeout can cancel an incomplete shutdown without detaching those resources.
- Telegram shutdown retains ongoing cleanup across a timeout or cancellation so a retry can finish it. Stopping during startup also cancels initialization and closes the partially initialized bot's HTTP clients before retiring its worker loop. If the Telegram loop has already stopped, shutdown warns that download clients may remain open and releases the abandoned cleanup state; later stops do not repeat that warning.
- Slack stop waits up to five seconds for an in-flight Socket Mode connection and its cleanup. If cleanup is still pending, the previous instance stays tracked and a restart can be retried after it finishes. SDK cleanup failures report their original error and remain retryable.
- In Telegram private chats, text, attachment and streaming replies (including "Working on it...") can still be delivered if their referenced user or bot message was deleted, such as after clearing chat history during a run. Group reply-target requirements remain unchanged to preserve forum routing.
- In Telegram groups, replying to a delivered bot response or attachment continues its DeerFlow conversation. Reply mappings survive restarts and stay scoped to the user's connection when one is bound. New, unrelated group messages still start separate conversations; private-chat routing is unchanged.
- New Telegram final-reply sends use the bot API's rate-limit wait up to 60 seconds per retry. Missing, invalid, or shorter hints use the usual backoff. The "Working on it..." acknowledgment is best effort.
- Feishu/Lark now queues rapid follow-up messages per mapped DeerFlow `thread_id` instead of immediately surfacing the generic busy reply, and topic replies keep a per-message card with a compact source-message preview across queued/running/final patches.
- Streaming IM channels treat backend `error` events like transport failures and follow the same reply and retry path. The channel logs the error type and message for diagnosis.

Set the corresponding API keys in your `.env` file:

```bash
# Telegram
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrSTUvwxYZ

# Slack
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...

# Feishu / Lark
FEISHU_APP_ID=cli_xxxx
FEISHU_APP_SECRET=your_app_secret

# WeChat iLink
WECHAT_BOT_TOKEN=your_ilink_bot_token
WECHAT_ILINK_BOT_ID=your_ilink_bot_id

# WeCom
WECOM_BOT_ID=your_bot_id
WECOM_BOT_SECRET=your_bot_secret

# DingTalk
DINGTALK_CLIENT_ID=your_client_id
DINGTALK_CLIENT_SECRET=your_client_secret
```

**Telegram Setup**

1. Chat with [@BotFather](https://t.me/BotFather), send `/newbot`, and copy the HTTP API token.
2. Set `TELEGRAM_BOT_TOKEN` in `.env` and enable the channel in `config.yaml`.
3. The bot accepts inbound text, photos, and documents (with or without captions). Hosted Bot API downloads are limited to 20 MB per attachment.

**Slack Setup**

1. Create a Slack App at [api.slack.com/apps](https://api.slack.com/apps) → Create New App → From scratch.
2. Under **OAuth & Permissions**, add Bot Token Scopes: `app_mentions:read`, `chat:write`, `im:history`, `im:read`, `im:write`, `files:write`.
3. Enable **Socket Mode** → generate an App-Level Token (`xapp-…`) with `connections:write` scope.
4. Under **Event Subscriptions**, subscribe to bot events: `app_mention`, `message.im`.
5. Set `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` in `.env` and enable the channel in `config.yaml`.

**Feishu / Lark Setup**

1. Create an app on [Feishu Open Platform](https://open.feishu.cn/) → enable **Bot** capability.
2. Add permissions: `im:message`, `im:message.p2p_msg:readonly`, `im:resource`.
3. Under **Events**, subscribe to `im.message.receive_v1` and select **Long Connection** mode.
4. Copy the App ID and App Secret. Set `FEISHU_APP_ID` and `FEISHU_APP_SECRET` in `.env` and enable the channel in `config.yaml`.
5. The bot supports inbound text, image, and file messages. Inbound attachment downloads are limited to 20 MB per attachment. A reply longer than one card (about 8,000 CJK characters) continues in further cards, up to 10 per answer.
6. _(Optional)_ Interactive clarification cards: set `card_interaction_enabled: true` under `channels.feishu` to let the agent's option-based clarifications render as clickable button cards, preserving any background context before the question. Then, in the developer console, open **Callback Configuration** (回调配置 — a separate tab from **Event Subscriptions**), subscribe to `card.action.trigger` in **Long Connection** mode, and publish a new app version. A click resolves the clarification exactly like typing the choice; only the user who triggered the clarification can operate its card. Button answers are saved in the conversation history, and subsequent clarifications continue in the same thread.

If the SDK repeatedly logs `CERTIFICATE_VERIFY_FAILED`, see [Feishu / Lark TLS troubleshooting](../../backend/docs/IM_CHANNEL_CONNECTIONS.md#feishu--lark-tls-troubleshooting) to check the Gateway's CA trust configuration.

Scheduled-task result and lifecycle notices can also be pushed to a bound Feishu/Lark user, without a new inbound message. They use the same notification outbox and localized summaries as WeCom. The app must be able to send to that user; see [Feishu scheduled-task notifications](../../backend/docs/IM_CHANNEL_CONNECTIONS.md#feishu-scheduled-task-notifications).

**WeChat Setup**

1. Enable the `wechat` channel in `config.yaml`.
2. Either set `WECHAT_BOT_TOKEN` in `.env`, or set `qrcode_login_enabled: true` for first-time QR bootstrap.
3. When `bot_token` is absent and QR bootstrap is enabled, watch backend logs for the QR content returned by iLink and complete the binding flow.
4. After the QR flow succeeds, DeerFlow persists the acquired token under `state_dir` for later restarts.
5. For Docker Compose deployments, keep `state_dir` on a persistent volume so the `get_updates_buf` cursor and saved auth state survive restarts.
6. Outbound images/files enforce `max_outbound_image_bytes` / `max_outbound_file_bytes` (20 MiB / 50 MiB defaults) while reading, including files that grow after resolution. Oversize reads are rejected before encryption/upload instead of sending a truncated prefix. Non-positive limits disable the corresponding cap.
7. `allowed_users` takes iLink user IDs. Unset, `null`, `[]`, or a blank string allows everyone. A single ID is one entry, not a sequence of characters, and an unquoted integer-valued number is stored as that integer's text. A scalar string containing commas or interior whitespace logs a warning but remains one literal ID; use a YAML list for multiple IDs. Invalid entries are ignored with a warning; any other configured value that yields no valid ID denies every user and logs an error. `/connect` is still accepted before that check, and a denied sender is dropped before inbound media is downloaded.
8. Shutdown waits for in-flight cursor writes. On token expiry, DeerFlow persists the cursor reset and removes the saved token before completing poller cancellation.
9. Inbound attachments keep separate staged copies even when filenames match within one message or across messages. Their original filenames are preserved for upload ingestion. Private staged copies are removed after ingestion or when a message is dropped or fails.
10. WeChat server long-poll hints are accepted from 1 through 300 seconds. Invalid hints leave the last accepted value in use, or `polling_timeout` if no hint has been accepted. Set `respect_server_longpoll_timeout: false` to always use the configured value.

**WeCom Setup**

1. Create a bot on the WeCom AI Bot platform and obtain the `bot_id` and `bot_secret`.
2. Enable `channels.wecom` in `config.yaml` and fill in `bot_id` / `bot_secret`.
3. Set `WECOM_BOT_ID` and `WECOM_BOT_SECRET` in `.env`.
4. Make sure backend dependencies include `wecom-aibot-python-sdk`. The channel uses a WebSocket long connection and does not require a public callback URL.
5. The current integration supports inbound text, image, and file messages. Final images/files generated by the agent are also sent back to the WeCom conversation.

**DingTalk Setup**

1. Create a DingTalk application in the [DingTalk Developer Console](https://open.dingtalk.com/) and enable **Robot** capability.
2. Set the message receiving mode to **Stream Mode** in the robot configuration page.
3. Copy the `Client ID` and `Client Secret`, set `DINGTALK_CLIENT_ID` and `DINGTALK_CLIENT_SECRET` in `.env`, and enable the channel in `config.yaml`.
4. *(Optional)* To enable streaming AI Card replies (typewriter effect), create an **AI Card** template on the [DingTalk Card Platform](https://open.dingtalk.com/document/dingstart/typewriter-effect-streaming-ai-card), then set `card_template_id` in `config.yaml` to the template ID. You also need to apply for the `Card.Streaming.Write` and `Card.Instance.Write` permissions.

DingTalk's Markdown fallback displays tables as labeled blockquotes, preserving escaped pipes (`\|`) within cells and empty leading or trailing cells so values stay under the correct column labels.


DingTalk token caching uses a two-hour fallback when the provider's token lifetime is invalid or no longer than the five-minute refresh margin, avoiding a refresh on every request.

When DeerFlow runs in Docker Compose, IM channels execute inside the `gateway` container. In that case, do not point `channels.langgraph_url` or `channels.gateway_url` at `localhost`; use container service names such as `http://gateway:8001/api` and `http://gateway:8001`, or set `DEER_FLOW_CHANNELS_LANGGRAPH_URL` and `DEER_FLOW_CHANNELS_GATEWAY_URL`.

**Commands**

Once a channel is connected, you can interact with DeerFlow directly from the chat:

| Command | Description |
|---------|-------------|
| `/new` | Start a new conversation |
| `/status` | Show current thread info |
| `/models` | List available models |
| `/model [name\|default]` | Show or pin the current conversation's model |
| `/memory` | View memory |
| `/agent list` | List your Custom Agents |
| `/agent use <name>` | Start a new conversation with a Custom Agent |
| `/help` | Show help |

> Messages without a command prefix are treated as regular chat — DeerFlow creates a thread and responds conversationally.

Agent selection is conversation-scoped: `/agent use <name>` starts a fresh conversation and pins that Custom Agent in the thread metadata. Existing conversations never switch agents midway, the selection survives a Gateway restart, and opening the IM-created thread in the Web UI continues through the same Custom Agent.
Use `/agent use lead_agent` to return to the default agent in a new conversation.

Model selection is conversation-scoped too: `/model <name>` pins a model to the *current* conversation — validated against the caller-visible model list, persisted in the thread metadata so it survives a Gateway restart, and applied from the next message without starting a new conversation. `/model` shows the effective model and its source, `/model default` clears the pin, and `/models` reports the pinned model.
