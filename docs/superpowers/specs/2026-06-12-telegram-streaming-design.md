# Telegram 流式输出设计

日期：2026-06-12
分支：`feat/telegram-streaming`
状态：已与用户确认

## 背景与目标

Telegram 通道目前完全不流式：`ChannelManager._handle_chat()` 走 `client.runs.wait()` 阻塞路径，agent 跑完后一次性 `send_message` 发出最终文本。用户先看到 "Working on it..."，然后长时间无反馈。

目标：让 Telegram 与飞书行为一致——通过编辑同一条消息的方式流式展示所有 AI 文本增量（manager 现有流式管线产出的累积文本），最终以 `is_final=True` 的完整结果收尾。

## 方案选型

- **方案 A（采纳）**：channel 侧自适配。只改 `telegram.py` + `CHANNEL_CAPABILITIES` 一行，Telegram 通道自己做编辑节流与限速容错。不触碰飞书/微信/钉钉共享的 manager 流式代码路径。
- 方案 B（否决）：manager 支持 per-channel `stream_min_interval` 节流。语义更统一，但改动共享路径，回归面大。

## 改动 1 — `backend/app/channels/manager.py`

`CHANNEL_CAPABILITIES["telegram"]["supports_streaming"]` 由 `False` 改为 `True`。

生效后 manager 自动走 `_handle_streaming_chat()`：
- 持续向 bus 发布 `is_final=False` 的 `OutboundMessage`（全量累积文本，manager 级节流 0.35s）；
- 流结束（或出错）时必发一条 `is_final=True` 的完整结果（含 artifacts/attachments）。

无其他 manager 改动。

## 改动 2 — `backend/app/channels/telegram.py`

### 流式状态

- 新增 `self._stream_messages: dict[str, dict]`，key 为 `f"{chat_id}:{thread_ts}"`（`thread_ts` 是触发本轮对话的用户消息 id，inbound/outbound 全程透传）。
- value 记录：`message_id`（正在被编辑的 bot 消息）、`last_edit_at`（节流时间戳）、`last_text`（已渲染文本，用于跳过无变化编辑）。

### 占位消息复用

`_send_running_reply()` 发出的 "Working on it..." 消息记录其 `message_id` 并登记到 `_stream_messages`。第一条流式更新直接编辑该占位消息。

### `send()` 按 `is_final` 分流

**`is_final=False`（流式更新）：**
1. 节流：距同 key 上次成功编辑 < 1.0 秒（群聊 `chat_id` 为负数时为 3.0 秒，因 Telegram 群有 20 条/分钟上限）→ 直接丢弃本次更新（安全：每条更新都是全量文本，final 必达兜底）。
2. 文本与 `last_text` 相同 → 跳过。
3. 已登记流式消息 → `edit_message_text`；未登记（占位发送失败等）→ `send_message` 新建并登记。
4. 文本 > 4096 字符 → 截断到 4095 并以 `…` 结尾后再编辑。

**`is_final=True`（最终结果）：**
1. 文本 ≤ 4096：对登记的流式消息做最终一次 `edit_message_text`。
2. 文本 > 4096：第一段（4096 内）编辑流式消息，剩余按 4096 分段 `send_message` 补发。
3. 清理该 key 的 `_stream_messages` 状态；用最后一条消息 id 更新 `_last_bot_message[chat_id]`（保持现有 threaded-reply 行为）。
4. 无登记流式消息时退回现行 `send_message` 逻辑（含现有 3 次重试）。注意：命令回复与 `_send_error` 错误回复带有匹配的 `thread_ts` 且占位消息已登记，因此同样走「编辑占位消息」路径（有意的 UX 改进），而非直发新消息。

### 错误处理

- `telegram.error.RetryAfter`(429)：丢弃本次流式更新，不重试不等待（下次更新自带全量文本）；final 路径遇 429 则按 `retry_after` 等待后重试，保证最终结果送达。
- `BadRequest: message is not modified`：静默忽略（final 文本与最后一帧相同时必然出现）。
- 其他编辑失败（如消息被用户删除）：回退 `send_message` 发新消息并更新登记。

### 不变项

- 纯文本发送，不引入 `parse_mode`（无 Markdown 解析失败风险）。
- `send_file()` 附件流程不动；attachments 仅随 final 消息到达，时序不变。
- 非流式直发（无登记状态的 `is_final=True`）行为与现状完全一致。

## 测试

新增 Telegram 流式用例（参照 `tests/test_channels.py` 中飞书流式用例的 fake-bot 模式）：

1. 多条 `is_final=False`：首条编辑占位消息，后续继续编辑同一 `message_id`。
2. 1 秒内密集更新被节流丢弃；final 仍完整送达。
3. final 超 4096：首段编辑 + 余段分段补发，`_last_bot_message` 指向最后一段。
4. `message is not modified` 被静默忽略，不计为失败。
5. 占位消息缺失时首条流式更新退化为 `send_message` 新建。
6. 无流式状态的 `is_final=True` 直发路径行为不变（回归保护）。

## 风险

- Telegram 对单 chat 的编辑限速较严（约 1 次/秒）。1s channel 侧节流 + 429 丢帧策略是飞书 0.35s 间隔在 Telegram 上的等价物；最坏情况是中间帧丢失，最终完整性由 `is_final=True` 保证。
- 群聊多话题并发：key 含 `thread_ts`，不同话题的流式互不串扰。
