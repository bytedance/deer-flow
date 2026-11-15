# Browser live view (`components/workspace/browser-view/`)

```bash
cd frontend && pnpm rstest run browser-view
```

- **Each socket attempt has its own handshake deadline.** A timeout retires the
  attempt and schedules the existing bounded backoff, without waiting for a later
  socket event. The deadline covers the connecting state only. An established
  quiet stream has no client idle timeout.
- **A retired attempt changes nothing.** Its callbacks cannot reset the retry
  budget, update frames or accept input.
- **`closedReason` is `handshake_timeout` or `connection_failed`.** WebSocket
  error and close events cannot reliably identify an auth, origin or network
  failure, so the UI does not claim one.
- **The latest failure reason stays visible during retries**, also over a
  retained frame, and clears on open, disable or thread change. Exhausted retries
  must not look pending.
