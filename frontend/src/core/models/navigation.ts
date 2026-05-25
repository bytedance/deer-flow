/**
 * Cross-page navigation context — unified jump protocol between main chain pages.
 *
 * Every cross-page navigation carries a serialized CrossPageContext so that
 * the destination page can display source breadcrumbs and the jump itself
 * is traceable for observability.
 */

export interface CrossPageContext {
  /** Where the user came from */
  sourceType: "chat" | "report" | "artifact";
  /** Identifier meaningful for that source type (thread_id, report_run_id, or artifact path) */
  sourceId: string;
  /** Owning thread */
  threadId: string;
  /** Specific run within the thread (optional — may not exist for pending runs) */
  runId?: string;
}

const CTX_KEY = "from";

/** Serialise CrossPageContext into a URL query parameter. */
export function encodeCrossPageContext(ctx: CrossPageContext): string {
  const payload: Record<string, string> = {
    sourceType: ctx.sourceType,
    sourceId: ctx.sourceId,
    threadId: ctx.threadId,
  };
  if (ctx.runId) payload.runId = ctx.runId;
  return encodeURIComponent(btoa(JSON.stringify(payload)));
}

/** Parse CrossPageContext from URLSearchParams. Returns null if absent or invalid. */
export function decodeCrossPageContext(
  searchParams: URLSearchParams,
): CrossPageContext | null {
  const raw = searchParams.get(CTX_KEY);
  if (!raw) return null;
  try {
    const obj = JSON.parse(atob(decodeURIComponent(raw)));
    if (
      typeof obj.sourceType === "string" &&
      typeof obj.sourceId === "string" &&
      typeof obj.threadId === "string"
    ) {
      return {
        sourceType: obj.sourceType as CrossPageContext["sourceType"],
        sourceId: obj.sourceId,
        threadId: obj.threadId,
        runId: typeof obj.runId === "string" ? obj.runId : undefined,
      };
    }
    return null;
  } catch {
    return null;
  }
}

/** Build a URL with CrossPageContext as a query parameter. */
export function buildCrossPageURL(
  pathname: string,
  ctx: CrossPageContext,
): string {
  const encoded = encodeCrossPageContext(ctx);
  return `${pathname}?${CTX_KEY}=${encoded}`;
}

/**
 * Generate a short, human-readable trace identifier for cross-page jumps.
 *
 * Format: "{sourceType}:{sourceId_short}:{timestamp}"
 * Example: "chat:abc123-4:2026-05-22T10"
 *
 * This identifier is logged to console and can be forwarded to observability
 * backends for troubleshooting broken navigation chains.
 */
export function createTraceId(ctx: CrossPageContext): string {
  const short = ctx.sourceId.slice(0, 8);
  const ts = new Date().toISOString().replace(/:\d{2}\.\d{3}Z$/, "");
  return `${ctx.sourceType}:${short}:${ts}`;
}

/** Log a cross-page navigation event for observability. */
export function logCrossPageNavigation(
  ctx: CrossPageContext,
  direction: "outbound" | "inbound",
): void {
  const traceId = createTraceId(ctx);
  const label =
    direction === "outbound" ? "CrossPageJump →" : "CrossPageJump ←";
  const timestamp = new Date().toISOString();
  console.info(
    `[${label}] trace=${traceId} sourceType=${ctx.sourceType} sourceId=${ctx.sourceId} threadId=${ctx.threadId} runId=${ctx.runId ?? "-"}`,
  );
  console.info("[CrossPageJump]", {
    traceId,
    direction,
    sourceType: ctx.sourceType,
    sourceId: ctx.sourceId,
    threadId: ctx.threadId,
    runId: ctx.runId ?? null,
    timestamp,
  });
}
