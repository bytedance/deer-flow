# Browser Live

`useBrowserStream` owns a 10-second opening-handshake deadline per socket
attempt. Timeout retires that attempt and schedules the existing bounded
backoff without depending on a later socket event. Open/error/close and effect
cleanup clear the deadline; retired callbacks cannot reset the retry budget,
update frames, or accept input. Keep the deadline limited to CONNECTING; an
established quiet stream has no client idle timeout.

Lifecycle regressions live in
`frontend/tests/unit/components/workspace/browser-view/use-browser-stream.dom.test.tsx`.
