"use client";

import { ChevronRightIcon } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo } from "react";

import {
  decodeCrossPageContext,
  logCrossPageNavigation,
  type CrossPageContext,
} from "@/core/models/navigation";
import { pathOfThread } from "@/core/threads/utils";
import { cn } from "@/lib/utils";

const SOURCE_LABELS: Record<CrossPageContext["sourceType"], string> = {
  chat: "对话",
  report: "报告",
  artifact: "产物",
};

interface SourceBreadcrumbProps {
  className?: string;
  /** Current page type (for display purposes) */
  currentLabel?: string;
}

/**
 * Breadcrumb that displays the source from which the user navigated.
 *
 * Reads CrossPageContext from URL search params. When present, shows
 * "← 来自{source} → 当前页" style breadcrumb. Logs inbound navigation
 * for observability.
 *
 * Works on any main chain page: chat, report run detail, artifact viewer.
 */
export function SourceBreadcrumb({
  className,
  currentLabel,
}: SourceBreadcrumbProps) {
  const searchParams = useSearchParams();
  const ctx = useMemo(() => decodeCrossPageContext(searchParams), [searchParams]);

  useEffect(() => {
    if (ctx) logCrossPageNavigation(ctx, "inbound");
  }, [ctx]);

  if (!ctx) return null;

  const sourceLabel = SOURCE_LABELS[ctx.sourceType] ?? ctx.sourceType;

  const sourceHref =
    ctx.sourceType === "report"
      ? `/workspace/report-runs/${ctx.sourceId}`
      : pathOfThread(ctx.threadId);

  return (
    <div
      className={cn(
        "flex items-center gap-1.5 text-xs text-muted-foreground",
        className,
      )}
    >
      <span>来自</span>
      <Link
        href={sourceHref}
        className="underline-offset-2 hover:underline"
      >
        {sourceLabel}
      </Link>
      {currentLabel && (
        <>
          <ChevronRightIcon className="size-3" />
          <span className="text-foreground">{currentLabel}</span>
        </>
      )}
    </div>
  );
}
