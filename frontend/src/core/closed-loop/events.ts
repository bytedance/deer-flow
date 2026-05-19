/**
 * Lightweight closure-event subscription hook.
 *
 * The backend publishes ``closure.<action>`` events through the existing
 * ``run_event`` channel during agent runs (see backend
 * ``deerflow.closed_loop.events``). The frontend already receives those
 * events on the active thread via the LangGraph stream, but the workspace
 * Closed-Loop page is **outside** any specific thread — so we can't piggyback
 * on a thread stream there.
 *
 * Two refresh strategies are available:
 *
 * 1. ``useClosureRefresh()`` — polling at a configurable interval (default
 *    30s). Cheap, robust, no infra changes. Used by the workspace list /
 *    kanban / nav badge.
 * 2. ``onClosureEvent(callback)`` — a thin event-bus that thread-stream code
 *    can call when it observes a ``closure.*`` ``run_event`` payload, so the
 *    list / drawer auto-invalidate. Wired up by call sites that already
 *    consume the LangGraph stream.
 */

import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { closureQueryKeys } from "./hooks";

const DEFAULT_REFRESH_INTERVAL_MS = 30_000;

type Listener = (action: string) => void;
const listeners = new Set<Listener>();

/** Notify all subscribers that a `closure.<action>` event was observed. */
export function emitClosureEvent(action: string): void {
  for (const listener of listeners) {
    try {
      listener(action);
    } catch {
      // best-effort — never let a misbehaving listener crash the bus
    }
  }
}

/**
 * Subscribe to closure events. Returns an unsubscribe fn.
 *
 * Call sites that already consume the LangGraph thread stream should
 * forward observed ``closure.<action>`` payloads via {@link emitClosureEvent}.
 */
export function onClosureEvent(callback: Listener): () => void {
  listeners.add(callback);
  return () => {
    listeners.delete(callback);
  };
}

/**
 * Background refresh for closure-ticket queries. Combines polling with the
 * event bus so the workspace stays current whether or not a stream is
 * available.
 */
export function useClosureRefresh(opts?: { intervalMs?: number }): void {
  const queryClient = useQueryClient();
  const intervalMs = opts?.intervalMs ?? DEFAULT_REFRESH_INTERVAL_MS;

  useEffect(() => {
    const invalidate = () => {
      void queryClient.invalidateQueries({ queryKey: closureQueryKeys.all });
    };
    const handle = window.setInterval(invalidate, intervalMs);
    const unsubscribe = onClosureEvent(invalidate);
    return () => {
      window.clearInterval(handle);
      unsubscribe();
    };
  }, [queryClient, intervalMs]);
}
