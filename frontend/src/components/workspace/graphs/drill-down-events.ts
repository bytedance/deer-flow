/**
 * Module-level event bus for chart drill-down interactions.
 * Uses the same useSyncExternalStore pattern as chart-themes.ts.
 */

export interface DrillDownFilter {
  chartTitle: string;
  seriesName: string;
  dimensionName: string;
  dimensionValue: string | number;
  dataIndex: number;
}

let _currentFilter: DrillDownFilter | null = null;
const _listeners = new Set<() => void>();

function notify() {
  for (const listener of _listeners) {
    listener();
  }
}

export function emitDrillDown(filter: DrillDownFilter) {
  _currentFilter = filter;
  notify();
}

export function clearDrillDown() {
  _currentFilter = null;
  notify();
}

export function getDrillDownFilter(): DrillDownFilter | null {
  return _currentFilter;
}

export function subscribeDrillDown(listener: () => void): () => void {
  _listeners.add(listener);
  return () => {
    _listeners.delete(listener);
  };
}
