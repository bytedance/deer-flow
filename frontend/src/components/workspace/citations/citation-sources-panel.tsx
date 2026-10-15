"use client";

import {
  BookOpenTextIcon,
  CheckIcon,
  CopyIcon,
  ExternalLinkIcon,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { bindArtifactURL } from "@/core/artifacts/utils";
import {
  formatCitationMarkdownReference,
  type CitationSource,
} from "@/core/citations/sources";
import { writeTextToClipboard } from "@/core/clipboard";
import { useI18n } from "@/core/i18n/hooks";
import { useWorkspaceLifetime } from "@/core/workspaces/context";
import { useCurrentWorkspaceView } from "@/core/workspaces/view-lifetime";
import { cn } from "@/lib/utils";

import { UnsafeLink } from "../messages/markdown-link";

export function CitationSourcesPanel({
  className,
  sources,
  resourceKey,
}: {
  className?: string;
  sources: CitationSource[];
  resourceKey?: string;
}) {
  const { t } = useI18n();
  const lifetime = useWorkspaceLifetime();

  if (sources.length === 0) {
    return null;
  }

  return (
    <details
      className={cn(
        "not-prose border-border/60 bg-muted/20 mt-2 rounded-md border text-xs",
        className,
      )}
    >
      <summary className="text-muted-foreground hover:text-foreground flex cursor-pointer list-none items-center gap-2 px-3 py-2 transition-colors [&::-webkit-details-marker]:hidden">
        <BookOpenTextIcon className="size-3.5 shrink-0" />
        <span className="font-medium">
          {t.citations.sourcesSummary(sources.length)}
        </span>
      </summary>
      <ol className="border-border/60 divide-border/60 max-h-80 divide-y overflow-y-auto overscroll-contain border-t">
        {sources.map((source, index) => {
          const href = bindArtifactURL(source.url, lifetime?.scope.workspaceId);
          const label = (
            <>
              <span className="min-w-0 flex-1">
                <span className="text-foreground block truncate font-medium">
                  {source.title}
                </span>
                <span className="text-muted-foreground block truncate">
                  {source.domain}
                </span>
              </span>
              <span className="text-muted-foreground shrink-0">
                {t.citations.citeCount(source.count)}
              </span>
              <ExternalLinkIcon className="text-muted-foreground size-3.5 shrink-0" />
            </>
          );
          const linkClass =
            "hover:bg-muted flex min-w-0 flex-1 items-center gap-2 rounded px-2 py-1 transition-colors";
          return (
            <li key={source.id} className="flex min-w-0 items-center gap-2 p-2">
              <span className="text-muted-foreground w-5 shrink-0 text-right tabular-nums">
                {index + 1}
              </span>
              {href === undefined ? (
                <UnsafeLink href={source.url} className={linkClass}>
                  {label}
                </UnsafeLink>
              ) : (
                <a
                  href={href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={linkClass}
                >
                  {label}
                </a>
              )}
              <CitationSourceCopyButton
                source={source}
                href={href}
                resourceKey={resourceKey}
              />
            </li>
          );
        })}
      </ol>
    </details>
  );
}

function CitationSourceCopyButton({
  source,
  href,
  resourceKey,
}: {
  source: CitationSource;
  href: string | undefined;
  resourceKey?: string;
}) {
  const { t } = useI18n();
  const isCurrent = useCurrentWorkspaceView(
    JSON.stringify([resourceKey, source.id, source.url, href, source.title]),
  );
  const [copiedOwner, setCopiedOwner] = useState<(() => boolean) | null>(null);
  const copied = copiedOwner === isCurrent;
  const resetTimerRef = useRef<{
    owner: () => boolean;
    handle: ReturnType<typeof setTimeout>;
  } | null>(null);
  const copyLabel = t.citations.copyReference(source.title);
  const copiedLabel = t.citations.copiedReference(source.title);

  useEffect(() => {
    return () => {
      const timer = resetTimerRef.current;
      if (timer?.owner === isCurrent) {
        clearTimeout(timer.handle);
        resetTimerRef.current = null;
      }
    };
  }, [isCurrent]);

  const handleCopy = useCallback(() => {
    if (!isCurrent() || href === undefined) return;
    void (async () => {
      const didCopy = await writeTextToClipboard(
        formatCitationMarkdownReference({ ...source, url: href }),
      );
      if (!isCurrent()) return;
      if (!didCopy) {
        toast.error(t.clipboard.failedToCopyToClipboard);
        return;
      }
      setCopiedOwner(() => isCurrent);
      toast.success(t.clipboard.copiedToClipboard);
      if (resetTimerRef.current) clearTimeout(resetTimerRef.current.handle);
      const handle: ReturnType<typeof setTimeout> = setTimeout(() => {
        if (!isCurrent() || resetTimerRef.current?.handle !== handle) return;
        setCopiedOwner(null);
        resetTimerRef.current = null;
      }, 2000);
      resetTimerRef.current = { owner: isCurrent, handle };
    })().catch(() => {
      if (isCurrent()) toast.error(t.clipboard.failedToCopyToClipboard);
    });
  }, [
    source,
    href,
    isCurrent,
    t.clipboard.copiedToClipboard,
    t.clipboard.failedToCopyToClipboard,
  ]);

  return (
    <button
      type="button"
      className="text-muted-foreground hover:bg-muted hover:text-foreground shrink-0 rounded p-1.5 transition-colors"
      aria-label={copied ? copiedLabel : copyLabel}
      title={copied ? copiedLabel : copyLabel}
      data-copied-label={copiedLabel}
      onClick={handleCopy}
      disabled={href === undefined}
    >
      {copied ? (
        <CheckIcon className="size-3.5 text-green-500" />
      ) : (
        <CopyIcon className="size-3.5" />
      )}
    </button>
  );
}
