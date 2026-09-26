# Telegram Streaming Output Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Telegram channel stream agent replies by editing one message in place (like Feishu's card patching), instead of waiting for the full result.

**Architecture:** Flip `supports_streaming` for Telegram so `ChannelManager._handle_streaming_chat()` publishes incremental `is_final=False` outbound updates (it already does this for Feishu — no manager logic changes). All adaptation lives in `TelegramChannel`: the "Working on it..." placeholder message is registered as the stream target, non-final updates `edit_message_text` it (channel-side 1s throttle, 4096-char truncation, drop-on-429), and the guaranteed `is_final=True` message performs the last edit (splitting >4096 texts into follow-up messages).

**Tech Stack:** Python 3.12, python-telegram-bot (mocked in tests), pytest.

**Spec:** `docs/superpowers/specs/2026-06-12-telegram-streaming-design.md`

**Branch:** `feat/telegram-streaming` (already created, spec committed)

**Key existing facts** (verified against the codebase):
- `OutboundMessage.is_final` defaults to `True` (`backend/app/channels/message_bus.py:119`), so error/command direct sends stay final.
- `ChannelManager._channel_supports_streaming()` (`backend/app/channels/manager.py:746`) prefers the **live channel instance's `supports_streaming` property** and falls back to `CHANNEL_CAPABILITIES`. Both must be updated.
- The streaming pipeline always publishes a final `is_final=True` message even on stream errors (`manager.py:1185-1224` `finally` block).
- `_send_running_reply()` is awaited **before** the inbound message is published (`telegram.py:324-326`), so the placeholder always exists before any outbound arrives.
- Outbound `thread_ts` equals the inbound `thread_ts`, which Telegram sets to the user message id (`telegram.py:397`). So the stream key `f"{chat_id}:{thread_ts}"` matches the placeholder registered with the user message id.
- Existing tests to keep green: `tests/test_channels.py::TestTelegramSendRetry` (send retry semantics, `_max_retries=0` RuntimeError).

**Intentional behavior change:** command replies (e.g. `/help`) and error replies now *edit* the "Working on it..." placeholder instead of sending a second message (key matches, `is_final=True`). This is improved UX and covered by a test.

Run tests from `backend/`: `PYTHONPATH=. uv run pytest tests/test_channels.py -v`

---

### Task 1: Capability flip — Telegram reports streaming support

**Files:**
- Modify: `backend/app/channels/manager.py:59` (CHANNEL_CAPABILITIES)
- Modify: `backend/app/channels/telegram.py` (add `supports_streaming` property)
- Test: `backend/tests/test_channels.py` (new class `TestTelegramStreaming`)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_channels.py` (bottom of file). The file already imports `MessageBus`, `OutboundMessage`, `ChannelManager`, `pytest`, `SimpleNamespace`, `MagicMock`, `AsyncMock`, and defines `_run()`:

```python
# ---------------------------------------------------------------------------
# Telegram streaming tests
# ---------------------------------------------------------------------------


class TestTelegramStreaming:
    def test_telegram_reports_streaming_support(self):
        from app.channels.manager import CHANNEL_CAPABILITIES
        from app.channels.telegram import TelegramChannel

        bus = MessageBus()
        ch = TelegramChannel(bus=bus, config={"bot_token": "test-token"})
        assert ch.supports_streaming is True
        assert CHANNEL_CAPABILITIES["telegram"]["supports_streaming"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. uv run pytest tests/test_channels.py::TestTelegramStreaming::test_telegram_reports_streaming_support -v`
Expected: FAIL with `assert False is True` (base class property returns False).

- [ ] **Step 3: Implement**

In `backend/app/channels/manager.py:59` change:

```python
    "telegram": {"supports_streaming": False},
```

to:

```python
    "telegram": {"supports_streaming": True},
```

In `backend/app/channels/telegram.py`, add a property right after `__init__` (before `async def start`):

```python
    @property
    def supports_streaming(self) -> bool:
        return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. uv run pytest tests/test_channels.py::TestTelegramStreaming -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/channels/manager.py backend/app/channels/telegram.py backend/tests/test_channels.py
git commit -m "feat(telegram): report streaming support for telegram channel"
```

---

### Task 2: Stream state infrastructure + placeholder registration

**Files:**
- Modify: `backend/app/channels/telegram.py` (constants, `__init__`, helpers, `_send_running_reply`)
- Test: `backend/tests/test_channels.py` (`TestTelegramStreaming`)

- [ ] **Step 1: Write the failing test**

Add to `TestTelegramStreaming`:

```python
    def test_running_reply_registers_stream_placeholder(self):
        from app.channels.telegram import TelegramChannel

        async def go():
            bus = MessageBus()
            ch = TelegramChannel(bus=bus, config={"bot_token": "test-token"})

            mock_app = MagicMock()
            mock_bot = AsyncMock()
            sent = MagicMock()
            sent.message_id = 777
            mock_bot.send_message = AsyncMock(return_value=sent)
            mock_app.bot = mock_bot
            ch._application = mock_app

            await ch._send_running_reply("12345", 42)

            state = ch._stream_messages["12345:42"]
            assert state["message_id"] == 777
            assert state["last_text"] == "Working on it..."
            mock_bot.send_message.assert_awaited_once_with(
                chat_id=12345,
                text="Working on it...",
                reply_to_message_id=42,
            )

        _run(go())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. uv run pytest tests/test_channels.py::TestTelegramStreaming::test_running_reply_registers_stream_placeholder -v`
Expected: FAIL with `AttributeError: 'TelegramChannel' object has no attribute '_stream_messages'`

- [ ] **Step 3: Implement**

In `backend/app/channels/telegram.py`:

a) Add `import time` to the imports block at the top (after `import threading`), and module constants after `logger = logging.getLogger(__name__)`:

```python
TELEGRAM_MAX_MESSAGE_LENGTH = 4096
STREAM_EDIT_MIN_INTERVAL_SECONDS = 1.0

# Indirection so tests can patch the clock without touching the global time module.
_monotonic = time.monotonic
```

b) In `__init__`, after `self._last_bot_message: dict[str, int] = {}`:

```python
        # stream_key ("chat_id:thread_ts") -> state of the in-flight streamed
        # bot message being edited in place: {"message_id", "last_edit_at", "last_text"}
        self._stream_messages: dict[str, dict[str, Any]] = {}
```

c) Add helpers in the `# -- helpers --` section (before `_send_running_reply`):

```python
    @staticmethod
    def _stream_key(chat_id: str, thread_ts: str | None) -> str:
        return f"{chat_id}:{thread_ts or ''}"

    @staticmethod
    def _is_retry_after(exc: Exception) -> bool:
        return getattr(exc, "retry_after", None) is not None

    @staticmethod
    def _retry_after_seconds(exc: Exception) -> float:
        value = getattr(exc, "retry_after", 0)
        if hasattr(value, "total_seconds"):
            return float(value.total_seconds())
        return float(value)

    @staticmethod
    def _is_not_modified(exc: Exception) -> bool:
        return "message is not modified" in str(exc).lower()

    @staticmethod
    def _split_message(text: str) -> list[str]:
        return [text[i : i + TELEGRAM_MAX_MESSAGE_LENGTH] for i in range(0, len(text), TELEGRAM_MAX_MESSAGE_LENGTH)] or [text]
```

d) Replace `_send_running_reply` (`telegram.py:183-196`) with:

```python
    async def _send_running_reply(self, chat_id: str, reply_to_message_id: int) -> None:
        """Send a 'Working on it...' reply and register it as the stream target."""
        if not self._application:
            return
        try:
            bot = self._application.bot
            sent = await bot.send_message(
                chat_id=int(chat_id),
                text="Working on it...",
                reply_to_message_id=reply_to_message_id,
            )
            self._stream_messages[self._stream_key(chat_id, str(reply_to_message_id))] = {
                "message_id": sent.message_id,
                "last_edit_at": 0.0,
                "last_text": "Working on it...",
            }
            logger.info("[Telegram] 'Working on it...' reply sent in chat=%s", chat_id)
        except Exception:
            logger.exception("[Telegram] failed to send running reply in chat=%s", chat_id)
```

- [ ] **Step 4: Run tests to verify pass (including existing retry tests)**

Run: `PYTHONPATH=. uv run pytest tests/test_channels.py::TestTelegramStreaming tests/test_channels.py::TestTelegramSendRetry -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/channels/telegram.py backend/tests/test_channels.py
git commit -m "feat(telegram): register running-reply placeholder as stream target"
```

---

### Task 3: Refactor `send()` — extract `_send_new_message` (no behavior change)

**Files:**
- Modify: `backend/app/channels/telegram.py:97-137` (`send`)
- Test: existing `tests/test_channels.py::TestTelegramSendRetry` must stay green

- [ ] **Step 1: Replace `send()` with the dispatching version + extracted helper**

Replace the whole `send()` method (`telegram.py:97-137`) with:

```python
    async def send(self, msg: OutboundMessage, *, _max_retries: int = 3) -> None:
        if not self._application:
            return

        try:
            chat_id = int(msg.chat_id)
        except (ValueError, TypeError):
            logger.error("Invalid Telegram chat_id: %s", msg.chat_id)
            return

        await self._send_new_message(chat_id, msg.chat_id, msg.text, _max_retries=_max_retries)

    async def _send_new_message(self, chat_id: int, chat_key: str, text: str, *, _max_retries: int = 3) -> int | None:
        """Send a fresh message with retry/backoff. Returns the sent message_id."""
        kwargs: dict[str, Any] = {"chat_id": chat_id, "text": text}

        # Reply to the last bot message in this chat for threading
        reply_to = self._last_bot_message.get(chat_key)
        if reply_to:
            kwargs["reply_to_message_id"] = reply_to

        bot = self._application.bot
        last_exc: Exception | None = None
        for attempt in range(_max_retries):
            try:
                sent = await bot.send_message(**kwargs)
                self._last_bot_message[chat_key] = sent.message_id
                return sent.message_id
            except Exception as exc:
                last_exc = exc
                if attempt < _max_retries - 1:
                    delay = 2**attempt  # 1s, 2s
                    logger.warning(
                        "[Telegram] send failed (attempt %d/%d), retrying in %ds: %s",
                        attempt + 1,
                        _max_retries,
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)

        logger.error("[Telegram] send failed after %d attempts: %s", _max_retries, last_exc)
        if last_exc is None:
            raise RuntimeError("Telegram send failed without an exception from any attempt")
        raise last_exc
```

- [ ] **Step 2: Run existing retry tests to verify no regression**

Run: `PYTHONPATH=. uv run pytest tests/test_channels.py::TestTelegramSendRetry tests/test_channels.py::TestTelegramStreaming -v`
Expected: all PASS (pure refactor)

- [ ] **Step 3: Commit**

```bash
git add backend/app/channels/telegram.py
git commit -m "refactor(telegram): extract _send_new_message from send()"
```

---

### Task 4: Non-final stream updates — edit in place with throttle/truncate/fallback

**Files:**
- Modify: `backend/app/channels/telegram.py` (`send`, new `_send_stream_update`)
- Test: `backend/tests/test_channels.py` (`TestTelegramStreaming`)

- [ ] **Step 1: Write the failing tests**

Add to `TestTelegramStreaming`. First add a shared fake-bot factory at the top of the class:

```python
    @staticmethod
    def _make_channel_with_bot():
        from app.channels.telegram import TelegramChannel

        bus = MessageBus()
        ch = TelegramChannel(bus=bus, config={"bot_token": "test-token"})

        mock_app = MagicMock()
        bot = SimpleNamespace()
        bot.sent = []
        bot.edited = []
        bot.next_message_id = 100

        async def send_message(**kwargs):
            bot.sent.append(kwargs)
            result = MagicMock()
            result.message_id = bot.next_message_id
            bot.next_message_id += 1
            return result

        async def edit_message_text(**kwargs):
            bot.edited.append(kwargs)
            result = MagicMock()
            result.message_id = kwargs["message_id"]
            return result

        bot.send_message = send_message
        bot.edit_message_text = edit_message_text
        mock_app.bot = bot
        ch._application = mock_app
        return ch, bot
```

Then the tests:

```python
    def test_stream_updates_edit_placeholder_in_place(self, monkeypatch):
        async def go():
            ch, bot = self._make_channel_with_bot()

            clock = {"now": 1000.0}
            monkeypatch.setattr("app.channels.telegram._monotonic", lambda: clock["now"])

            await ch._send_running_reply("12345", 42)
            placeholder_id = ch._stream_messages["12345:42"]["message_id"]

            update1 = OutboundMessage(channel_name="telegram", chat_id="12345", thread_id="t1", text="Hello", is_final=False, thread_ts="42")
            await ch.send(update1)

            clock["now"] += 2.0
            update2 = OutboundMessage(channel_name="telegram", chat_id="12345", thread_id="t1", text="Hello world", is_final=False, thread_ts="42")
            await ch.send(update2)

            assert len(bot.sent) == 1  # only the placeholder
            assert [e["message_id"] for e in bot.edited] == [placeholder_id, placeholder_id]
            assert [e["text"] for e in bot.edited] == ["Hello", "Hello world"]

        _run(go())

    def test_stream_updates_throttled_within_interval(self, monkeypatch):
        async def go():
            ch, bot = self._make_channel_with_bot()

            clock = {"now": 1000.0}
            monkeypatch.setattr("app.channels.telegram._monotonic", lambda: clock["now"])

            await ch._send_running_reply("12345", 42)

            await ch.send(OutboundMessage(channel_name="telegram", chat_id="12345", thread_id="t1", text="a", is_final=False, thread_ts="42"))
            clock["now"] += 0.3  # within 1s window -> dropped
            await ch.send(OutboundMessage(channel_name="telegram", chat_id="12345", thread_id="t1", text="ab", is_final=False, thread_ts="42"))
            clock["now"] += 1.0  # past window -> edited
            await ch.send(OutboundMessage(channel_name="telegram", chat_id="12345", thread_id="t1", text="abc", is_final=False, thread_ts="42"))

            assert [e["text"] for e in bot.edited] == ["a", "abc"]

        _run(go())

    def test_stream_update_without_placeholder_sends_new_message(self):
        async def go():
            ch, bot = self._make_channel_with_bot()

            await ch.send(OutboundMessage(channel_name="telegram", chat_id="12345", thread_id="t1", text="Hi", is_final=False, thread_ts="42"))

            assert len(bot.sent) == 1
            assert bot.sent[0]["text"] == "Hi"
            assert ch._stream_messages["12345:42"]["message_id"] == 100

        _run(go())

    def test_stream_update_truncates_long_text(self, monkeypatch):
        async def go():
            ch, bot = self._make_channel_with_bot()

            clock = {"now": 1000.0}
            monkeypatch.setattr("app.channels.telegram._monotonic", lambda: clock["now"])

            await ch._send_running_reply("12345", 42)
            long_text = "x" * 5000
            await ch.send(OutboundMessage(channel_name="telegram", chat_id="12345", thread_id="t1", text=long_text, is_final=False, thread_ts="42"))

            assert len(bot.edited) == 1
            assert len(bot.edited[0]["text"]) == 4096
            assert bot.edited[0]["text"].endswith("…")

        _run(go())

    def test_stream_update_retry_after_is_dropped(self, monkeypatch):
        async def go():
            ch, bot = self._make_channel_with_bot()

            clock = {"now": 1000.0}
            monkeypatch.setattr("app.channels.telegram._monotonic", lambda: clock["now"])

            await ch._send_running_reply("12345", 42)

            async def edit_rate_limited(**kwargs):
                exc = Exception("Flood control exceeded")
                exc.retry_after = 5
                raise exc

            bot.edit_message_text = edit_rate_limited
            # Must not raise, must not send a new message
            await ch.send(OutboundMessage(channel_name="telegram", chat_id="12345", thread_id="t1", text="Hi", is_final=False, thread_ts="42"))
            assert len(bot.sent) == 1  # placeholder only

        _run(go())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. uv run pytest tests/test_channels.py::TestTelegramStreaming -v`
Expected: the new tests FAIL (current `send()` sends new messages for every outbound; `bot.sent` counts are wrong).

- [ ] **Step 3: Implement**

In `backend/app/channels/telegram.py`, replace the `send()` body and add `_send_stream_update`:

```python
    async def send(self, msg: OutboundMessage, *, _max_retries: int = 3) -> None:
        if not self._application:
            return

        try:
            chat_id = int(msg.chat_id)
        except (ValueError, TypeError):
            logger.error("Invalid Telegram chat_id: %s", msg.chat_id)
            return

        key = self._stream_key(msg.chat_id, msg.thread_ts)

        if not msg.is_final:
            await self._send_stream_update(chat_id, key, msg.text)
            return

        await self._send_new_message(chat_id, msg.chat_id, msg.text, _max_retries=_max_retries)

    async def _send_stream_update(self, chat_id: int, key: str, text: str) -> None:
        """Edit the in-flight streamed message with accumulated text.

        Updates are best-effort: throttled, rate-limit drops are silent.  The
        manager always publishes a final message afterwards, which guarantees
        delivery of the complete text.
        """
        if not text:
            return

        display = text
        if len(display) > TELEGRAM_MAX_MESSAGE_LENGTH:
            display = display[: TELEGRAM_MAX_MESSAGE_LENGTH - 1] + "…"

        bot = self._application.bot
        state = self._stream_messages.get(key)

        if state is None:
            try:
                sent = await bot.send_message(chat_id=chat_id, text=display)
            except Exception:
                logger.exception("[Telegram] failed to start stream message in chat=%s", chat_id)
                return
            self._stream_messages[key] = {
                "message_id": sent.message_id,
                "last_edit_at": _monotonic(),
                "last_text": display,
            }
            return

        now = _monotonic()
        if now - state["last_edit_at"] < STREAM_EDIT_MIN_INTERVAL_SECONDS:
            return
        if display == state["last_text"]:
            return

        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=state["message_id"], text=display)
        except Exception as exc:
            if self._is_not_modified(exc):
                state["last_text"] = display
                return
            if self._is_retry_after(exc):
                logger.debug("[Telegram] stream edit rate-limited in chat=%s, dropping update", chat_id)
                return
            logger.warning("[Telegram] stream edit failed in chat=%s, sending new message: %s", chat_id, exc)
            try:
                sent = await bot.send_message(chat_id=chat_id, text=display)
            except Exception:
                logger.exception("[Telegram] failed to send fallback stream message in chat=%s", chat_id)
                return
            state["message_id"] = sent.message_id

        state["last_edit_at"] = _monotonic()
        state["last_text"] = display
```

- [ ] **Step 4: Run tests to verify pass**

Run: `PYTHONPATH=. uv run pytest tests/test_channels.py::TestTelegramStreaming tests/test_channels.py::TestTelegramSendRetry -v`
Expected: all PASS. Note `TestTelegramSendRetry` still passes because its messages default to `is_final=True` with no registered stream state.

- [ ] **Step 5: Commit**

```bash
git add backend/app/channels/telegram.py backend/tests/test_channels.py
git commit -m "feat(telegram): edit streamed message in place for non-final updates"
```

---

### Task 5: Final message — last edit, >4096 split, cleanup

**Files:**
- Modify: `backend/app/channels/telegram.py` (`send`, new `_finalize_stream_message`)
- Test: `backend/tests/test_channels.py` (`TestTelegramStreaming`)

- [ ] **Step 1: Write the failing tests**

Add to `TestTelegramStreaming`:

```python
    def test_final_message_edits_stream_message_and_clears_state(self, monkeypatch):
        async def go():
            ch, bot = self._make_channel_with_bot()

            clock = {"now": 1000.0}
            monkeypatch.setattr("app.channels.telegram._monotonic", lambda: clock["now"])

            await ch._send_running_reply("12345", 42)
            placeholder_id = ch._stream_messages["12345:42"]["message_id"]

            await ch.send(OutboundMessage(channel_name="telegram", chat_id="12345", thread_id="t1", text="partial", is_final=False, thread_ts="42"))
            await ch.send(OutboundMessage(channel_name="telegram", chat_id="12345", thread_id="t1", text="full answer", is_final=True, thread_ts="42"))

            assert [e["text"] for e in bot.edited] == ["partial", "full answer"]
            assert len(bot.sent) == 1  # placeholder only — final edited, not re-sent
            assert "12345:42" not in ch._stream_messages
            assert ch._last_bot_message["12345"] == placeholder_id

        _run(go())

    def test_final_message_splits_long_text(self, monkeypatch):
        async def go():
            ch, bot = self._make_channel_with_bot()

            clock = {"now": 1000.0}
            monkeypatch.setattr("app.channels.telegram._monotonic", lambda: clock["now"])

            await ch._send_running_reply("12345", 42)
            long_text = "a" * 4096 + "b" * 100

            await ch.send(OutboundMessage(channel_name="telegram", chat_id="12345", thread_id="t1", text=long_text, is_final=True, thread_ts="42"))

            assert len(bot.edited) == 1
            assert bot.edited[0]["text"] == "a" * 4096
            follow_ups = bot.sent[1:]  # bot.sent[0] is the placeholder
            assert [m["text"] for m in follow_ups] == ["b" * 100]
            # Fake bot assigns ids sequentially: placeholder=100, follow-up chunk=101
            assert ch._last_bot_message["12345"] == 101
            assert "12345:42" not in ch._stream_messages

        _run(go())

    def test_final_message_not_modified_error_is_ignored(self, monkeypatch):
        async def go():
            ch, bot = self._make_channel_with_bot()

            clock = {"now": 1000.0}
            monkeypatch.setattr("app.channels.telegram._monotonic", lambda: clock["now"])

            await ch._send_running_reply("12345", 42)
            await ch.send(OutboundMessage(channel_name="telegram", chat_id="12345", thread_id="t1", text="done", is_final=False, thread_ts="42"))

            async def edit_not_modified(**kwargs):
                raise Exception("Bad Request: message is not modified")

            bot.edit_message_text = edit_not_modified
            # Same text again as final — must not raise, must not send a new message
            await ch.send(OutboundMessage(channel_name="telegram", chat_id="12345", thread_id="t1", text="done", is_final=True, thread_ts="42"))

            assert len(bot.sent) == 1  # placeholder only
            assert "12345:42" not in ch._stream_messages

        _run(go())

    def test_final_without_stream_state_sends_plain_message(self):
        async def go():
            ch, bot = self._make_channel_with_bot()

            await ch.send(OutboundMessage(channel_name="telegram", chat_id="12345", thread_id="t1", text="direct", is_final=True, thread_ts=None))

            assert len(bot.sent) == 1
            assert bot.sent[0]["text"] == "direct"
            assert len(bot.edited) == 0

        _run(go())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. uv run pytest tests/test_channels.py::TestTelegramStreaming -v`
Expected: new tests FAIL (final messages currently always go through `_send_new_message`).

- [ ] **Step 3: Implement**

In `backend/app/channels/telegram.py`, update `send()`'s final branch and add `_finalize_stream_message`:

```python
    async def send(self, msg: OutboundMessage, *, _max_retries: int = 3) -> None:
        if not self._application:
            return

        try:
            chat_id = int(msg.chat_id)
        except (ValueError, TypeError):
            logger.error("Invalid Telegram chat_id: %s", msg.chat_id)
            return

        key = self._stream_key(msg.chat_id, msg.thread_ts)

        if not msg.is_final:
            await self._send_stream_update(chat_id, key, msg.text)
            return

        state = self._stream_messages.pop(key, None)
        if state is not None:
            await self._finalize_stream_message(chat_id, msg.chat_id, state, msg.text)
            return

        await self._send_new_message(chat_id, msg.chat_id, msg.text, _max_retries=_max_retries)

    async def _finalize_stream_message(self, chat_id: int, chat_key: str, state: dict[str, Any], text: str) -> None:
        """Apply the final text: edit the streamed message, splitting overflow into follow-ups."""
        bot = self._application.bot
        chunks = self._split_message(text or "")
        last_message_id = state["message_id"]

        if chunks[0] != state["last_text"]:
            try:
                await bot.edit_message_text(chat_id=chat_id, message_id=state["message_id"], text=chunks[0])
            except Exception as exc:
                if self._is_not_modified(exc):
                    pass
                elif self._is_retry_after(exc):
                    await asyncio.sleep(self._retry_after_seconds(exc))
                    await bot.edit_message_text(chat_id=chat_id, message_id=state["message_id"], text=chunks[0])
                else:
                    logger.warning("[Telegram] final edit failed in chat=%s, sending new message: %s", chat_id, exc)
                    sent = await bot.send_message(chat_id=chat_id, text=chunks[0])
                    last_message_id = sent.message_id

        for chunk in chunks[1:]:
            sent = await bot.send_message(chat_id=chat_id, text=chunk)
            last_message_id = sent.message_id

        self._last_bot_message[chat_key] = last_message_id
```

- [ ] **Step 4: Run the full channel test file**

Run: `PYTHONPATH=. uv run pytest tests/test_channels.py -v`
Expected: all PASS (including Feishu/WeCom/manager tests — none of their code paths were touched).

- [ ] **Step 5: Run telegram connection tests too**

Run: `PYTHONPATH=. uv run pytest tests/test_telegram_channel_connections.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/channels/telegram.py backend/tests/test_channels.py
git commit -m "feat(telegram): finalize streamed message with overflow splitting"
```

---

### Task 6: Documentation + full test suite

**Files:**
- Modify: `backend/CLAUDE.md` (IM Channels section)
- Modify: `README.md` (only if it mentions Telegram non-streaming — check first)

- [ ] **Step 1: Update backend/CLAUDE.md**

In the "IM Channels System" section, two spots:

1. The `manager.py` component bullet currently reads:

> `manager.py` - Core dispatcher: creates threads via `client.threads.create()`, routes commands, keeps Slack/Telegram on `client.runs.wait()`, and uses `client.runs.stream(["messages-tuple", "values"])` for Feishu incremental outbound updates

Change to:

> `manager.py` - Core dispatcher: creates threads via `client.threads.create()`, routes commands, keeps Slack/Discord on `client.runs.wait()`, and uses `client.runs.stream(["messages-tuple", "values"])` for Feishu/Telegram incremental outbound updates

2. The Message Flow items 5-6 currently read:

> 5. Feishu chat: `runs.stream()` → accumulate AI text → publish multiple outbound updates (`is_final=False`) → publish final outbound (`is_final=True`)
> 6. Slack/Telegram chat: `runs.wait()` → extract final response → publish outbound

Change to:

> 5. Feishu/Telegram chat: `runs.stream()` → accumulate AI text → publish multiple outbound updates (`is_final=False`) → publish final outbound (`is_final=True`)
> 6. Slack/Discord chat: `runs.wait()` → extract final response → publish outbound

3. Add a bullet after the Feishu card-patching item (item 7):

> 8. Telegram streaming: the "Working on it..." placeholder message is registered as the stream target; non-final updates `editMessageText` it in place (1s channel-side throttle, 4096-char truncation, 429 updates dropped); the final update performs the last edit and splits >4096 texts into follow-up messages

(Renumber the following items accordingly.)

- [ ] **Step 2: Check README mentions**

Run: `grep -rn "Telegram" README.md docs/ --include="*.md" -l | head`
If any doc states Telegram does not stream, update it the same way. If none, skip.

- [ ] **Step 3: Run the full backend test suite**

Run from `backend/`: `make test`
Expected: all PASS.

- [ ] **Step 4: Lint**

Run from `backend/`: `make lint`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add backend/CLAUDE.md README.md docs/
git commit -m "docs: telegram channel now streams replies via message editing"
```

---

## Self-Review Notes

- **Spec coverage:** capability flip (Task 1), placeholder reuse (Task 2), throttle/truncate/429-drop/fallback-new-message (Task 4), final edit/split/cleanup/not-modified/RetryAfter-wait (Task 5), direct-send regression protection (Task 5 `test_final_without_stream_state_sends_plain_message` + existing `TestTelegramSendRetry`), docs (Task 6). Spec test list items 1-6 all map to concrete tests.
- **Type consistency:** `_stream_messages: dict[str, dict[str, Any]]` keys `message_id`/`last_edit_at`/`last_text` used identically in Tasks 2, 4, 5. `_send_new_message(chat_id: int, chat_key: str, text: str)` signature consistent between Tasks 3 and 5.
- **Known trade-off:** the final-path fallback `send_message` in `_finalize_stream_message` has no retry loop (single attempt, exception propagates to `_on_outbound` which logs and skips file uploads — same contract as today's `send()` failure).
