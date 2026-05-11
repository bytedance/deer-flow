import { type ComponentType, lazy } from "react";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type LazyComponent = ComponentType<any>;

/* eslint-disable @typescript-eslint/no-explicit-any */
const COMPONENT_REGISTRY: Record<string, () => Promise<{ default: LazyComponent }>> = {
  chart: () => import("@/components/genui/ChartBlock") as any,
  echart: () => import("@/components/genui/EChartBlock") as any,
  table: () => import("@/components/genui/TableBlock") as any,
  card: () => import("@/components/genui/CardBlock") as any,
  form: () => import("@/components/genui/FormBlock") as any,
  confirm: () => import("@/components/genui/ConfirmBlock") as any,
  code: () => import("@/components/genui/CodeBlock") as any,
  timeline: () => import("@/components/genui/TimelineBlock") as any,
  layout: () => import("@/components/genui/LayoutBlock") as any,
  markdown: () => import("@/components/genui/MarkdownBlock") as any,
};
/* eslint-enable @typescript-eslint/no-explicit-any */

const SUPPORTED_MAJOR_VERSION = 1;

const componentCache = new Map<string, React.LazyExoticComponent<LazyComponent>>();

function parseMajorVersion(version: string): number {
  const major = parseInt(version.split(".")[0] ?? "0", 10);
  return isNaN(major) ? 0 : major;
}

export function getBlockComponent(
  componentType: string,
  schemaVersion: string,
): React.LazyExoticComponent<LazyComponent> | null {
  const major = parseMajorVersion(schemaVersion);
  if (major > SUPPORTED_MAJOR_VERSION) {
    return getBlockComponent("markdown", "1.0");
  }

  const loader = COMPONENT_REGISTRY[componentType];
  if (!loader) {
    return null;
  }

  const cached = componentCache.get(componentType);
  if (cached) {
    return cached;
  }

  const LazyComp = lazy(loader);
  componentCache.set(componentType, LazyComp);
  return LazyComp;
}

export function isKnownComponent(componentType: string): boolean {
  return componentType in COMPONENT_REGISTRY;
}
