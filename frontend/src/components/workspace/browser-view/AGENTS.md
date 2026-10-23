# Browser Live

`useBrowserStream` owns a 10-second opening-handshake deadline per socket
attempt. Timeout retires that attempt and schedules the existing bounded
backoff without depending on a later socket event. Open/error/close and effect
cleanup clear the deadline; retired callbacks cannot reset the retry budget,
update frames, or accept input. Keep the deadline limited to CONNECTING; an
established quiet stream has no client idle timeout.

Expose `closedReason` as `handshake_timeout` or `connection_failed`; WebSocket
error/close events cannot reliably identify auth, origin, or network failures.
Keep the latest failure reason visible during retries; fence retired callbacks;
clear it on open, disable, or thread change. The panel localizes the reason and
recovery hint even over a retained frame; exhausted retries must not look pending.

Lifecycle regressions live in
`frontend/tests/unit/components/workspace/browser-view/use-browser-stream.dom.test.tsx`;
panel feedback is covered by the adjacent `browser-view-panel.dom.test.tsx`.
