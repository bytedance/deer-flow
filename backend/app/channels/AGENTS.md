# IM channels (`app/channels/`)

Each provider module adapts one chat platform to the shared `MessageBus` and
`ChannelManager`. Channels are Gateway clients: they create threads and runs through
the LangGraph-compatible HTTP API with `langgraph-sdk`, and the Gateway owns the
thread lifecycle. Provider setup, flow diagrams and operator notes are in
[IM_CHANNEL_CONNECTIONS.md](../../docs/IM_CHANNEL_CONNECTIONS.md) and
[GITHUB_AGENTS.md](../../docs/GITHUB_AGENTS.md).

## Verify

```bash
cd backend
python -m pytest tests -q -k "channel or <provider>"   # e.g. telegram, feishu, wecom, qq
make test-blocking-io                                  # channels share the Gateway event loop
```

## Where the code misleads

- **Shared event loop.** All channels run on the Gateway event loop, which also
  serves HTTP requests. Run blocking SDK calls, file I/O and SDK teardown through
  `asyncio.to_thread`. When a provider SDK calls back from its own thread, submit
  work with `Channel._submit_threadsafe_coroutine()` so that the real task is
  retained and drained on `stop()`.
- **Stream text is an allowlist.** Middlewares inject hidden `HumanMessage`s
  (recalled memory, rewritten user turns) that also arrive on the `messages-tuple`
  stream. Publish only assistant message types to the platform. A denylist leaks
  hidden model context to chat users.
- **Several Gateway workers.** A leader lease decides which worker starts each
  transport, and thread bindings live in SQL so that replicas agree. State that
  you keep in process memory (caches, buffers, watchers) is invisible to the other
  workers; say so in the code when you add it. GitHub has no lease because it is
  webhook-driven.
- **Stop can time out.** `ChannelService` keeps a channel instance whose `stop()`
  timed out and retries it later. A new provider must make `stop()` safe to call
  again and must release SDK resources only after its own tasks have drained.
- **Final reply before dedupe release.** Publish the final outbound message before
  you release the inbound dedupe key. A provider redelivery can otherwise overtake
  the reply.
- **Goal handoff pins the saved thread.** Recheck the conversation binding after
  confirmation delivery and run preparation. Use run-admission evidence when
  reporting a rejected start or a response lost after submission.
- **Telegram photo fallback is narrow.** Only a photo `BadRequest` with
  `PHOTO_INVALID_DIMENSIONS` or `IMAGE_PROCESS_FAILED` is retried, once, as a
  document with the same bytes, file name and reply target. Other errors and
  cancellation keep their behavior. Count only the delivery that succeeds.
- **Docker networking.** Channels run inside the `gateway` container, so
  `localhost` in `channels.langgraph_url` / `channels.gateway_url` points at that
  container. Compose deployments use `http://gateway:8001`.

## Identity and security

- **Owner versus sender.** For a user-owned connection, the DeerFlow owner becomes
  the run `user_id` and the platform sender stays `channel_user_id`. Put
  `channel_user_id` in the runtime context only. `configurable` is checkpointed
  and would persist one sender's identity for the whole group thread.
- **One storage owner per message.** Resolve the storage owner once in the manager
  and pass it as `user_id=` through every file helper. Uploads and outbound
  artifacts then use the same bucket as the agent run. Resolve outbound artifacts
  through `app.gateway.path_utils.resolve_outputs_confined_path`, which rejects
  paths and symlinks that leave `outputs/`.
- **Connect codes run before allowlists.** `/connect <code>` (Telegram
  `/start <code>`) is handled before `allowed_users` on purpose, so that a new user
  can bind. The code is the secret: show it only in the browser that requested it
  and never echo it to the chat.
- **Feishu post commands use the caption.** Add placeholders for top-level post
  attachments after command detection. For commands that enter the chat path,
  `receive_file` adds their placeholders after the manager parses the arguments.
- **One active owner per external identity.** A partial unique index in the
  database enforces this. Application code alone cannot, because two workers can
  bind at the same time.
- **Inbound media.** Fetch provider media only from the URL and hosts that the
  channel validated, enforce the size limit while streaming, and pass the bytes to
  the shared upload pipeline. Bot API file URLs contain the bot token; keep them
  out of messages, metadata and logs.
- **Logs.** Log identifiers and error names. Keep credentials, message content and
  provider response bodies out of the logs.

## GitHub channel

- The webhook route skips session auth and CSRF because the HMAC signature
  authenticates it. It is mounted only when `GITHUB_WEBHOOK_SECRET` is set.
- Outbound is log-only by design. Each agent posts its own comment with `gh` from
  its sandbox, so the manager starts the run and does not wait for it.
- Follow-up buffering while a thread is busy is process-local. Read
  [the contract](../../docs/GITHUB_AGENTS.md#follow-up-buffering-while-busy-4121)
  before you change it.

## Adding a provider

Keep the service, provider, credential and config registrations aligned in the
same change. Buzz
needs the `buzz` dependency extra, and its relay delivers chat events only to
channel-scoped subscriptions
([details](../../docs/IM_CHANNEL_CONNECTIONS.md#buzz-subscription-model)).
