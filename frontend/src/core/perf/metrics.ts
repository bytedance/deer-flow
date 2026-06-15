/**
 * Frontend performance metrics for SSE streaming optimization.
 *
 * Tracks three key indicators:
 * 1. Active SSE connection count (including GenUISSEManager)
 * 2. /ui-blocks/extract call frequency
 * 3. Main thread Long Task count via Performance Observer
 *
 * Usage:
 *   import { perfMetrics } from "@/core/perf/metrics";
 *   perfMetrics.start();
 *   // ... run operations ...
 *   const snapshot = perfMetrics.snapshot();
 */

interface PerfSnapshot {
  activeSSEConnections: number;
  uiBlocksExtractCalls: number;
  longTaskCount: number;
  longTaskTotalMs: number;
  timestamp: number;
}

class PerfMetrics {
  private _activeSSE = 0;
  private _uiBlocksExtractCalls = 0;
  private _longTaskCount = 0;
  private _longTaskTotalMs = 0;
  private _observer: PerformanceObserver | null = null;
  private _running = false;

  start(): void {
    if (this._running) return;
    this._running = true;
    this._activeSSE = 0;
    this._uiBlocksExtractCalls = 0;
    this._longTaskCount = 0;
    this._longTaskTotalMs = 0;

    if (typeof PerformanceObserver !== "undefined" && "supports" in PerformanceObserver) {
      try {
        if (PerformanceObserver.supportedEntryTypes.includes("longtask")) {
          this._observer = new PerformanceObserver((list) => {
            for (const entry of list.getEntries()) {
              this._longTaskCount++;
              this._longTaskTotalMs += entry.duration;
            }
          });
          this._observer.observe({ entryTypes: ["longtask"] });
        }
      } catch {
        // longtask not supported in this environment
      }
    }
  }

  stop(): void {
    this._running = false;
    this._observer?.disconnect();
    this._observer = null;
  }

  incrementSSE(): void {
    this._activeSSE++;
  }

  decrementSSE(): void {
    this._activeSSE = Math.max(0, this._activeSSE - 1);
  }

  recordUIBlocksExtract(): void {
    this._uiBlocksExtractCalls++;
  }

  snapshot(): PerfSnapshot {
    return {
      activeSSEConnections: this._activeSSE,
      uiBlocksExtractCalls: this._uiBlocksExtractCalls,
      longTaskCount: this._longTaskCount,
      longTaskTotalMs: Math.round(this._longTaskTotalMs),
      timestamp: Date.now(),
    };
  }

  reset(): void {
    this._activeSSE = 0;
    this._uiBlocksExtractCalls = 0;
    this._longTaskCount = 0;
    this._longTaskTotalMs = 0;
  }
}

export const perfMetrics = new PerfMetrics();

export type { PerfSnapshot };
