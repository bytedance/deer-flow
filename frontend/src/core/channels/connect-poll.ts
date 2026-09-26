import type { ChannelConnection, ChannelProviderId } from "./types";

export const CONNECT_POLL_INTERVAL_MS = 2000;
// Fallback bind window used when the backend response omits or garbles
// `expires_in`, so a non-finite value can never produce an unbounded poll loop.
const DEFAULT_CONNECT_EXPIRES_S = 600;

export interface ConnectPollHandle {
  cancel: () => void;
}

export interface ConnectPollOptions {
  provider: ChannelProviderId;
  expiresInSeconds: number;
  /** Fetch the latest connections — the single source of truth for "connected". */
  fetchConnections: () => Promise<ChannelConnection[]>;
  /** Invoked once when the provider's connection resolves to "connected". */
  onConnected: () => void;
  intervalMs?: number;
  now?: () => number;
}

/**
 * Poll the connections endpoint until the given provider reports `connected`
 * or the bind window elapses. Returns a handle whose `cancel()` stops the loop
 * (used to dedup repeated connects and to clean up on unmount).
 *
 * Only the connections endpoint is polled; `onConnected` lets the caller refresh
 * derived provider state exactly once when the bind lands, instead of fetching
 * both endpoints on every tick.
 */
export function startConnectionPoll(
  options: ConnectPollOptions,
): ConnectPollHandle {
  const {
    provider,
    expiresInSeconds,
    fetchConnections,
    onConnected,
    intervalMs = CONNECT_POLL_INTERVAL_MS,
    now = Date.now,
  } = options;

  const expires =
    Number.isFinite(expiresInSeconds) && expiresInSeconds > 0
      ? expiresInSeconds
      : DEFAULT_CONNECT_EXPIRES_S;
  const deadline = now() + expires * 1000;

  let timer: ReturnType<typeof setTimeout> | undefined;
  let cancelled = false;

  const cancel = () => {
    cancelled = true;
    if (timer !== undefined) {
      clearTimeout(timer);
      timer = undefined;
    }
  };

  const schedule = () => {
    timer = setTimeout(() => {
      timer = undefined;
      if (cancelled) {
        return;
      }
      void fetchConnections()
        .then((connections) => {
          if (cancelled) {
            return;
          }
          const connected = connections.some(
            (item) => item.provider === provider && item.status === "connected",
          );
          if (connected) {
            onConnected();
            return;
          }
          if (now() < deadline) {
            schedule();
          }
        })
        .catch(() => {
          if (!cancelled && now() < deadline) {
            schedule();
          }
        });
    }, intervalMs);
  };

  schedule();
  return { cancel };
}
