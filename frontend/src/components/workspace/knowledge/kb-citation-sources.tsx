"use client";

import { BookOpenIcon, ChevronDown, ChevronRight } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { useI18n } from "@/core/i18n/hooks";
import type { KnowledgeCitation } from "@/core/knowledge/types";
import { cn } from "@/lib/utils";

import { ChunkCard } from "./chunk-card";
import { KB_CITATION_JUMP_EVENT, type CitationJumpDetail } from "./citation-mark";

/**
 * Citation cards under an assistant answer (spec §4.6/§3.6, phase-2 batch-1
 * P2). Collapsed by default into a one-line entry「参考来源 · N + 类型统计」;
 * expanding shows merged cards (same-document citations combine, numbers
 * shown together), capped at 5 with 查看全部. Chunk cards expand the shared
 * ChunkCard in place; wiki cards open the entry drawer via onOpenWikiEntry
 * (overlay — never switches the middle tab). A citation-mark click in the
 * answer body dispatches KB_CITATION_JUMP_EVENT: the strip expands, the
 * matching card highlights, and chunk cards auto-open the chunk text (so a
 * touch-device tap reaches the slice directly).
 */

const COLLAPSED_LIMIT = 5;
const HIGHLIGHT_MS = 2000;

type CitationGroup = {
  key: string;
  docName: string;
  sourceType: "chunk" | "wiki" | "manual";
  items: { number: number; citation: KnowledgeCitation }[];
};

function groupSources(sources: KnowledgeCitation[]): CitationGroup[] {
  const groups: CitationGroup[] = [];
  const byKey = new Map<string, CitationGroup>();
  sources.forEach((source, index) => {
    const sourceType = source.source_type ?? "chunk";
    const key = `${sourceType}:${source.doc_name}`;
    let group = byKey.get(key);
    if (!group) {
      group = { key, docName: source.doc_name, sourceType, items: [] };
      byKey.set(key, group);
      groups.push(group);
    }
    group.items.push({ number: index + 1, citation: source });
  });
  return groups;
}

export function KbCitationSources({
  sources,
  messageId,
  onOpenWikiEntry,
  kbId,
}: {
  sources: KnowledgeCitation[];
  messageId: string;
  onOpenWikiEntry?: (entryId: string) => void;
  /** Enables in-place chunk images (`images/…` → document files route). */
  kbId?: string;
}) {
  const { t } = useI18n();
  const tc = t.knowledge.chat;
  const [expanded, setExpanded] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [expandedChunkId, setExpandedChunkId] = useState<string | null>(null);
  const [highlightNumbers, setHighlightNumbers] = useState<number[]>([]);
  const rootRef = useRef<HTMLDivElement>(null);

  const groups = useMemo(() => groupSources(sources), [sources]);
  const chunkCount = useMemo(() => sources.filter((s) => (s.source_type ?? "chunk") === "chunk").length, [sources]);
  const wikiCount = useMemo(() => sources.filter((s) => s.source_type === "wiki").length, [sources]);
  // Phase-3 P6 (spec §8): manual cards cited through wiki_search.
  const manualCount = sources.length - chunkCount - wikiCount;

  // Citation-mark clicks in the answer body land here: expand + highlight
  // every matching card (a merged mark carries several display numbers),
  // auto-opening the first chunk/manual card's text so a touch tap reaches
  // the slice directly.
  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<CitationJumpDetail>).detail;
      if (detail?.messageId !== messageId) {
        return;
      }
      setExpanded(true);
      setHighlightNumbers(detail.indices);
      const matched = groups.filter((candidate) =>
        candidate.items.some((item) => detail.indices.includes(item.number)),
      );
      // Cards expand in place like chunks (no entry drawer for manual cards).
      const target = matched.find(
        (candidate) =>
          candidate.sourceType === "chunk" || candidate.sourceType === "manual",
      );
      if (target) {
        setExpandedChunkId(target.items[0]!.citation.chunk_id);
      }
      window.setTimeout(() => {
        // Scoped to this strip — a document-wide selector could scroll to a
        // highlight left over in ANOTHER message's sources.
        rootRef.current?.querySelector(`[data-citation-highlight="true"]`)?.scrollIntoView?.({ block: "nearest" });
      }, 0);
      window.setTimeout(() => setHighlightNumbers([]), HIGHLIGHT_MS);
    };
    window.addEventListener(KB_CITATION_JUMP_EVENT, handler);
    return () => window.removeEventListener(KB_CITATION_JUMP_EVENT, handler);
  }, [groups, messageId]);

  if (sources.length === 0) {
    return null;
  }

  const visibleGroups = showAll ? groups : groups.slice(0, COLLAPSED_LIMIT);
  const expandedSource =
    groups.flatMap((group) => group.items).find((item) => item.citation.chunk_id === expandedChunkId)?.citation ?? null;

  return (
    <div ref={rootRef} className="mt-3 flex flex-col gap-1.5" data-testid="kb-citation-sources">
      <button
        aria-expanded={expanded}
        className="text-muted-foreground hover:bg-muted/60 flex w-fit items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium transition-colors"
        type="button"
        onClick={() => setExpanded((value) => !value)}
      >
        <BookOpenIcon className="size-3.5" />
        <span>{tc.sourcesTitle(sources.length)}</span>
        {chunkCount > 0 && <span className="text-muted-foreground/80">· {tc.chunkSources(chunkCount)}</span>}
        {wikiCount > 0 && <span className="text-muted-foreground/80">· {tc.wikiSources(wikiCount)}</span>}
        {manualCount > 0 && <span className="text-muted-foreground/80">· {tc.manualSources(manualCount)}</span>}
        {expanded ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
      </button>

      {expanded && (
        <ol className="flex flex-col gap-1.5">
          {visibleGroups.map((group) => {
            const first = group.items[0]!;
            const isWiki = group.sourceType === "wiki";
            const typeLabel =
              group.sourceType === "wiki" ? tc.sourceTypeWiki : group.sourceType === "manual" ? tc.sourceTypeManual : tc.sourceTypeChunk;
            const isHighlighted = group.items.some((item) =>
              highlightNumbers.includes(item.number),
            );
            // Display numbers only: each item's number IS its sorted strip
            // position (the raw backend citation_nos are internal handles and
            // never shown), so the visible number space stays 1..N continuous
            // and one card carries exactly one number per merged slice.
            const numbers = group.items.map((item) => `[${item.number}]`).join("·");
            return (
              <li key={group.key}>
                <button
                  className={cn(
                    "hover:bg-muted/60 flex w-full flex-col gap-0.5 rounded-md border px-2.5 py-1.5 text-left transition-colors",
                    isHighlighted && "bg-muted/60 ring-1 ring-primary/40",
                  )}
                  data-citation-highlight={isHighlighted ? "true" : undefined}
                  data-testid={`citation-card-${group.sourceType}-${first.citation.chunk_id}`}
                  type="button"
                  onClick={() => {
                    if (isWiki) {
                      onOpenWikiEntry?.(first.citation.chunk_id);
                    } else {
                      setExpandedChunkId((current) => (current === first.citation.chunk_id ? null : first.citation.chunk_id));
                    }
                  }}
                >
                  <span className="flex w-full items-center gap-2 text-xs">
                    <span className="text-muted-foreground shrink-0 font-mono">{numbers}</span>
                    <Badge className="shrink-0 text-[10px]" variant="secondary">
                      {typeLabel}
                    </Badge>
                    <span className="min-w-0 flex-1 truncate font-medium">{group.docName}</span>
                    {first.citation.page != null && (
                      <span className="text-muted-foreground shrink-0">{tc.pageLabel(first.citation.page)}</span>
                    )}
                  </span>
                  {first.citation.heading_path.length > 0 && (
                    <span className="text-muted-foreground w-full truncate text-xs">{first.citation.heading_path.join(" / ")}</span>
                  )}
                  <span className="text-muted-foreground line-clamp-2 w-full text-xs">{first.citation.text.slice(0, 120)}</span>
                </button>
                {!isWiki && expandedChunkId === first.citation.chunk_id && expandedSource && (
                  <div className="mt-1 mb-1.5 ml-6">
                    {/* chunk_id 形如 `{doc_id}#0001`，前段即 doc_id（manual 卡片无图片引用，重写不生效也无碍） */}
                    <ChunkCard
                      docId={expandedSource.chunk_id.split("#")[0]}
                      docName={expandedSource.doc_name}
                      kbId={kbId}
                      page={expandedSource.page}
                      text={expandedSource.text}
                    />
                  </div>
                )}
              </li>
            );
          })}
          {!showAll && groups.length > COLLAPSED_LIMIT && (
            <li>
              <button
                className="text-muted-foreground hover:bg-muted/60 w-full rounded-md px-2.5 py-1 text-left text-xs"
                type="button"
                onClick={() => setShowAll(true)}
              >
                {tc.viewAllSources}（{groups.length}）
              </button>
            </li>
          )}
        </ol>
      )}
    </div>
  );
}
