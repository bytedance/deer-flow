# IM Channel Connections

DeerFlow supports user-owned IM channel connections for Telegram, Slack, and Discord. A logged-in user connects a provider from the frontend, and incoming IM messages run under that DeerFlow user account instead of the raw platform user id.

## Configuration

Enable the top-level `channel_connections` block in `config.yaml`:

Local/private deployment:

```yaml
channel_connections:
  enabled: true
  mode: local

  telegram:
    enabled: true
    bot_token: $TELEGRAM_BOT_TOKEN
    bot_username: $TELEGRAM_BOT_USERNAME
```

This mode is intended for a DeerFlow instance running on a developer machine or a private network. Telegram uses the existing long-polling worker, so it does not need a public URL. The frontend `Connect` button returns a Telegram deep link and stores a one-time state locally so the `/start` message can bind the Telegram chat to the current DeerFlow user.

Public deployment:

```yaml
channel_connections:
  enabled: true
  mode: public
  public_base_url: https://deerflow.example.com
  encryption_key: $DEER_FLOW_CHANNEL_CONNECTIONS_KEY

  telegram:
    enabled: true
    bot_token: $TELEGRAM_BOT_TOKEN
    bot_username: $TELEGRAM_BOT_USERNAME
    webhook_secret: $TELEGRAM_WEBHOOK_SECRET

  slack:
    enabled: true
    client_id: $SLACK_CLIENT_ID
    client_secret: $SLACK_CLIENT_SECRET
    signing_secret: $SLACK_SIGNING_SECRET
    event_delivery: http

  discord:
    enabled: true
    client_id: $DISCORD_CLIENT_ID
    client_secret: $DISCORD_CLIENT_SECRET
    bot_token: $DISCORD_BOT_TOKEN
    permissions: "274877975552"
```

`public_base_url` is only required for public callback/webhook deployments. If it is omitted, OAuth redirect URLs are built from the current request origin, which is suitable for localhost development when the provider allows an exact localhost redirect URI. Provider-to-server webhooks such as Slack HTTP Events and Telegram webhooks still need a reachable public URL or a tunnel.

`encryption_key` encrypts provider tokens at rest with Fernet. Telegram deep-link binding does not store user provider tokens, so it can run locally without this key. Slack and Discord connections store OAuth credentials and require a stable key; v1 does not support transparent key rotation, so changing it requires users to reconnect.

## Frontend Flow

The workspace sidebar shows a Channels group with Telegram, Slack, and Discord. Settings > Channels exposes the management surface for connect, disconnect, and reconnect. Browser state-changing calls use the existing CSRF-aware frontend fetch wrapper.

## Provider Setup

Telegram:

- Register a bot with BotFather.
- Configure the bot username and bot token.
- Users connect with a deep link: `https://t.me/<bot_username>?start=<state>`.
- Local/private delivery uses the existing long-polling channel worker and does not require `public_base_url`.
- Production webhook path: `POST /api/channels/webhooks/telegram`, protected by `X-Telegram-Bot-Api-Secret-Token`; webhook delivery requires `webhook_secret` and a public `public_base_url`.

Slack:

- Create a Slack app with OAuth V2.
- Redirect URL: `https://<public_base_url>/api/channels/slack/callback`.
- Event request URL: `https://<public_base_url>/api/channels/webhooks/slack/events`.
- Required signing secret: Slack's request signing secret, not the deprecated verification token.
- Suggested MVP bot scopes: `app_mentions:read`, `chat:write`, `channels:history`, `channels:read`.
- Slack events are signature-verified, deduplicated by `event_id`, and then routed to a matching user connection.
- In local/private mode, Slack HTTP Events are reported as unavailable unless `public_base_url` is set to a tunnel or public HTTPS URL.

Discord:

- Create a Discord application and bot.
- Redirect URL: `https://<public_base_url>/api/channels/discord/callback` in public mode, or the matching localhost callback URL in local development if the Discord application is configured to allow it.
- DeerFlow starts OAuth with `identify guilds bot applications.commands` and the configured bot permissions.
- The Discord Gateway is still handled by `discord.py`; message content may require the privileged Message Content Intent depending on your bot setup.

## Runtime Model

Connection records live in SQL tables under `deerflow.persistence.channel_connections`:

- `channel_connections`: owner user, provider identity, workspace/guild/team, status, metadata.
- `channel_credentials`: encrypted access/refresh/bot tokens.
- `channel_oauth_states`: one-time OAuth/deep-link states.
- `channel_conversations`: connection-scoped IM conversation to DeerFlow thread mapping.
- `channel_webhook_deliveries`: provider webhook dedupe records.

Incoming messages that resolve to a connection carry `connection_id`, `owner_user_id`, and `workspace_id`. `ChannelManager` uses `owner_user_id` as the DeerFlow run user id and preserves the platform user id as `channel_user_id`. Legacy operator-owned channels keep the existing JSON `ChannelStore` behavior when no `connection_id` is present.

## Security Notes

- OAuth state tokens are one-time and short-lived.
- Provider tokens are never returned from browser APIs.
- Public callback/webhook routes bypass cookie auth only because they validate provider state/signatures/secrets themselves.
- Slack and Telegram webhooks skip CSRF because they are called by providers, not browsers.
- Logs should never include access tokens, refresh tokens, bot tokens, OAuth codes, or raw signed webhook bodies.
