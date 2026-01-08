// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { ExternalLink, Globe, Clock, Star } from "lucide-react";
import { useMemo } from "react";

import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from "~/components/ui/hover-card";
import { cn } from "~/lib/utils";
import type { Citation } from "~/core/messages";

// Re-export Citation type as CitationData for backward compatibility
export type CitationData = Citation;

interface CitationLinkProps {
  href: string;
  children: React.ReactNode;
  citations: CitationData[];
  className?: string;
}

/**
 * Enhanced link component that shows citation metadata on hover.
 * Used within markdown content to provide rich citation information.
 */
export function CitationLink({
  href,
  children,
  citations,
  className,
}: CitationLinkProps) {
  // Find matching citation data for this URL
  const citation = useMemo(() => {
    if (!href || !citations) return null;
    
    // Try exact match first
    let match = citations.find((c) => c.url === href);
    
    // Try encoded/decoded match
    if (!match) {
      const decodedHref = decodeURIComponent(href);
      const encodedHref = encodeURI(href);
      match = citations.find(
        (c) =>
          c.url === decodedHref ||
          c.url === encodedHref ||
          decodeURIComponent(c.url) === decodedHref
      );
    }
    
    return match;
  }, [href, citations]);

  // If no citation data found, render as regular link
  if (!citation) {
    return (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className={cn("text-primary hover:underline", className)}
      >
        {children}
      </a>
    );
  }

  return (
    <HoverCard openDelay={200} closeDelay={100}>
      <HoverCardTrigger asChild>
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          className={cn(
            "text-primary hover:underline inline-flex items-center gap-0.5",
            className
          )}
        >
          {children}
          <span className="text-xs text-muted-foreground ml-0.5">
            <ExternalLink className="h-3 w-3 inline" />
          </span>
        </a>
      </HoverCardTrigger>
      <HoverCardContent
        className="w-80 p-4"
        side="top"
        align="start"
        sideOffset={8}
      >
        <CitationCard citation={citation} />
      </HoverCardContent>
    </HoverCard>
  );
}

interface CitationCardProps {
  citation: CitationData;
  compact?: boolean;
}

/**
 * Card component displaying citation metadata.
 */
export function CitationCard({ citation, compact = false }: CitationCardProps) {
  const {
    title,
    url,
    description,
    domain,
    relevance_score,
    accessed_at,
    source_type,
  } = citation;

  // Format access date
  const formattedDate = useMemo(() => {
    if (!accessed_at) return null;
    try {
      const date = new Date(accessed_at);
      return date.toLocaleDateString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
      });
    } catch {
      return accessed_at.slice(0, 10);
    }
  }, [accessed_at]);

  // Format relevance score as percentage
  const relevancePercent = useMemo(() => {
    if (relevance_score == null || relevance_score <= 0) return null;
    return Math.round(relevance_score * 100);
  }, [relevance_score]);

  return (
    <span className={cn("block space-y-2", compact && "space-y-1")}>
      {/* Title */}
      <span className="block font-semibold text-sm line-clamp-2 leading-snug">
        {title}
      </span>

      {/* Domain and metadata row */}
      <span className="flex items-center gap-3 text-xs text-muted-foreground">
        {domain && (
          <span className="flex items-center gap-1">
            <Globe className="h-3 w-3" />
            {domain}
          </span>
        )}
        {formattedDate && (
          <span className="flex items-center gap-1">
            <Clock className="h-3 w-3" />
            {formattedDate}
          </span>
        )}
        {relevancePercent != null && (
          <span className="flex items-center gap-1">
            <Star className="h-3 w-3" />
            {relevancePercent}% match
          </span>
        )}
      </span>

      {/* Description/snippet */}
      {description && !compact && (
        <span className="block text-xs text-muted-foreground line-clamp-3 leading-relaxed">
          {description}
        </span>
      )}

      {/* Source type badge */}
      {source_type && (
        <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] bg-secondary text-secondary-foreground">
          {source_type === "web_search" ? "Web" : source_type}
        </span>
      )}

      {/* URL preview */}
      <span className="block text-[10px] text-muted-foreground truncate opacity-60">
        {url}
      </span>
    </span>
  );
}

interface CitationListProps {
  citations: CitationData[];
  title?: string;
  className?: string;
}

/**
 * List component for displaying all citations.
 */
export function CitationList({
  citations,
  title = "Sources",
  className,
}: CitationListProps) {
  if (!citations || citations.length === 0) {
    return null;
  }

  return (
    <div className={cn("space-y-3", className)}>
      <h3 className="text-sm font-semibold text-foreground">{title}</h3>
      <div className="space-y-2">
        {citations.map((citation, index) => (
          <div
            key={citation.url || index}
            className="p-3 rounded-lg border bg-card hover:bg-accent/50 transition-colors"
          >
            <div className="flex items-start gap-3">
              <span className="flex-shrink-0 w-6 h-6 rounded-full bg-primary/10 text-primary text-xs font-medium flex items-center justify-center">
                {index + 1}
              </span>
              <div className="flex-1 min-w-0">
                <a
                  href={citation.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm font-medium text-foreground hover:text-primary hover:underline line-clamp-1"
                >
                  {citation.title}
                </a>
                {citation.domain && (
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {citation.domain}
                  </p>
                )}
                {citation.description && (
                  <p className="text-xs text-muted-foreground mt-1 line-clamp-2">
                    {citation.description}
                  </p>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

interface CitationBadgeProps {
  number: number;
  citation?: CitationData;
  onClick?: () => void;
}

/**
 * Small numbered badge for inline citations.
 */
export function CitationBadge({ number, citation, onClick }: CitationBadgeProps) {
  const badge = (
    <button
      onClick={onClick}
      className="inline-flex items-center justify-center w-4 h-4 rounded-full bg-primary/10 text-primary text-[10px] font-medium hover:bg-primary/20 transition-colors align-super ml-0.5 cursor-pointer"
    >
      {number}
    </button>
  );

  if (!citation) {
    return badge;
  }

  return (
    <HoverCard openDelay={200} closeDelay={100}>
      <HoverCardTrigger asChild>{badge}</HoverCardTrigger>
      <HoverCardContent className="w-72 p-3" side="top" sideOffset={4}>
        <CitationCard citation={citation} compact />
      </HoverCardContent>
    </HoverCard>
  );
}
