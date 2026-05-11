type TelemetryEventType =
  | "block_render_start"
  | "block_render_complete"
  | "block_render_error"
  | "interaction_submit"
  | "interaction_success"
  | "interaction_error"
  | "interaction_timeout";

interface TelemetryEvent {
  type: TelemetryEventType;
  component?: string;
  block_id?: string;
  callback_id?: string;
  duration_ms?: number;
  error?: string;
  timestamp: number;
}

const EVENT_BUFFER: TelemetryEvent[] = [];
const FLUSH_INTERVAL_MS = 10000;
const MAX_BUFFER_SIZE = 50;

let flushTimer: ReturnType<typeof setInterval> | null = null;

function getBackendBaseUrl(): string {
  if (typeof window !== "undefined") {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return ((window as any).__NEXT_PUBLIC_BACKEND_BASE_URL as string) ?? "";
  }
  return process.env.NEXT_PUBLIC_BACKEND_BASE_URL ?? "";
}

function startFlushTimer(): void {
  if (flushTimer) return;
  flushTimer = setInterval(() => {
    void flushEvents();
  }, FLUSH_INTERVAL_MS);
}

async function flushEvents(): Promise<void> {
  if (EVENT_BUFFER.length === 0) return;

  const events = EVENT_BUFFER.splice(0, EVENT_BUFFER.length);
  const baseUrl = getBackendBaseUrl();

  try {
    await fetch(`${baseUrl}/api/telemetry/genui`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ events }),
    });
  } catch {
    // Telemetry is best-effort; silently drop on failure
  }
}

export function trackEvent(
  type: TelemetryEventType,
  data?: Omit<TelemetryEvent, "type" | "timestamp">,
): void {
  const event: TelemetryEvent = {
    type,
    timestamp: Date.now(),
    ...data,
  };

  EVENT_BUFFER.push(event);
  startFlushTimer();

  if (EVENT_BUFFER.length >= MAX_BUFFER_SIZE) {
    void flushEvents();
  }
}

export function trackRenderStart(component: string, blockId: string): () => void {
  const start = performance.now();
  trackEvent("block_render_start", { component, block_id: blockId });

  return () => {
    const duration = performance.now() - start;
    trackEvent("block_render_complete", {
      component,
      block_id: blockId,
      duration_ms: Math.round(duration),
    });
  };
}

export function trackRenderError(
  component: string,
  blockId: string,
  error: string,
): void {
  trackEvent("block_render_error", { component, block_id: blockId, error });
}

export function trackInteraction(
  type: Extract<TelemetryEventType, `interaction_${string}`>,
  callbackId: string,
  extra?: { duration_ms?: number; error?: string },
): void {
  trackEvent(type, { callback_id: callbackId, ...extra });
}
