import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { getBackendBaseURL } from "@/core/config";

/**
 * Subscribes to the memory SSE endpoint and auto-invalidates
 * memory-related queries when events are received.
 *
 * Debounces refreshes to at most once per second.
 */
export function useMemoryEventSubscription() {
  const queryClient = useQueryClient();
  const lastRefreshRef = useRef(0);
  const pendingRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const url = `${getBackendBaseURL()}/api/memory/events`;
    const es = new EventSource(url);

    function scheduleRefresh() {
      const now = Date.now();
      const elapsed = now - lastRefreshRef.current;

      if (elapsed >= 1000) {
        lastRefreshRef.current = now;
        pendingRef.current = false;
        void queryClient.invalidateQueries({ queryKey: ["memory"] });
        void queryClient.invalidateQueries({ queryKey: ["session-memory"] });
        void queryClient.invalidateQueries({ queryKey: ["domain-memory"] });
        void queryClient.invalidateQueries({ queryKey: ["memory-audit"] });
      } else if (!pendingRef.current) {
        pendingRef.current = true;
        timerRef.current = setTimeout(scheduleRefresh, 1000 - elapsed);
      }
    }

    es.addEventListener("memory_updated", () => {
      scheduleRefresh();
    });

    es.addEventListener("error", () => {
      // EventSource auto-reconnects; no action needed
    });

    return () => {
      es.close();
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      pendingRef.current = false;
    };
  }, [queryClient]);
}
