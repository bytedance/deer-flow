import type { StreamMode } from "@langchain/langgraph-sdk";
import { usePathname } from "next/navigation";

import { type StreamModeTier, STREAM_MODE_TIERS } from "@/core/api/stream-mode";

const REPORT_PATH_PREFIXES = ["/workspace/report-templates", "/workspace/report-runs"];

export function isReportPage(pathname: string): boolean {
  return REPORT_PATH_PREFIXES.some((prefix) => pathname.startsWith(prefix));
}

export function useStreamTier(): StreamModeTier {
  const pathname = usePathname();
  return isReportPage(pathname) ? "full" : "standard";
}

export function useStreamModes(): readonly StreamMode[] {
  const tier = useStreamTier();
  return STREAM_MODE_TIERS[tier];
}

export interface StreamTierNotice {
  tier: StreamModeTier;
  message: string;
}

/**
 * Returns a user-facing notice when the current page uses the ``full`` stream
 * tier (report pages).  For ``standard`` tier pages, returns ``null``.
 *
 * The notice informs report-generation users that their experience is unchanged
 * — full stream modes (including ``values``) remain active.
 */
export function useStreamTierNotice(): StreamTierNotice | null {
  const tier = useStreamTier();
  if (tier !== "full") return null;
  return {
    tier,
    message: "报告页面使用完整流模式，行为未改变。",
  };
}
