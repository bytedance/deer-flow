"use client";

import { BookOpen, FileText, StickyNote } from "lucide-react";
import type { ComponentProps } from "react";

import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card";
import { useI18n } from "@/core/i18n/hooks";
import type { KnowledgeCitation } from "@/core/knowledge/types";

/**
 * Superscript citation mark (phase-2 batch-1, spec §4): the answer's ``[n]``
 * renders as a small muted superscript button — visually annotation-layer,
 * not body text. Hover shows preview cards (type badge + doc name + page /
 * heading path + ~120-char excerpt, reusing the citation's own ``text`` — no
 * new API); clicking dispatches ``KB_CITATION_JUMP_EVENT`` so the sources
 * strip expands and highlights the matching cards. On touch devices (no
 * hover) the tap still jumps — the strip auto-opens the chunk card.
 *
 * Merged marks (spec 2026-09-28-citation-mark-merge-quiet): one button may
 * carry several citations — the rehype plugin collapses whitespace-adjacent
 * ``[n]`` runs into ``data-citation-indices``, and the renderer shows the
 * group's display numbers sorted ascending and deduped, joined with ``,``
 * (a middle dot floats at mid-height and reads odd at superscript size). Hover stacks one preview card per
 * citation; the click highlights every matching card. The default style is a
 * quieter grey step (hover restores and lifts it) — dense annotation should
 * read as an annotation layer, not noise.
 */

export const KB_CITATION_JUMP_EVENT = "kb-citation-jump";

export type CitationJumpDetail = { messageId: string; indices: number[] };

export type CitationMarkItem = { citation: KnowledgeCitation; index: number };

export function CitationPreviewCard({ citation }: { citation: KnowledgeCitation }) {
  const { t } = useI18n();
  const tc = t.knowledge.chat;
  // Phase-3 P6 (spec §8): manual cards cited through wiki_search get their
  // own badge (「我的卡片」/StickyNote) alongside 百科/文档.
  const sourceType = citation.source_type ?? "chunk";
  const typeLabel = sourceType === "wiki" ? tc.sourceTypeWiki : sourceType === "manual" ? tc.sourceTypeManual : tc.sourceTypeChunk;
  return (
    <div className="flex flex-col gap-1.5" data-testid="citation-preview">
      <div className="flex items-center gap-1.5 text-xs">
        {sourceType === "wiki" ? (
          <BookOpen className="text-muted-foreground size-3.5" />
        ) : sourceType === "manual" ? (
          <StickyNote className="text-muted-foreground size-3.5" />
        ) : (
          <FileText className="text-muted-foreground size-3.5" />
        )}
        <span className="text-muted-foreground">{typeLabel}</span>
        <span className="min-w-0 flex-1 truncate font-medium">{citation.doc_name}</span>
        {citation.page != null && <span className="text-muted-foreground shrink-0">{tc.pageLabel(citation.page)}</span>}
      </div>
      {citation.heading_path.length > 0 && (
        <div className="text-muted-foreground truncate text-xs">{citation.heading_path.join(" / ")}</div>
      )}
      <p className="text-muted-foreground line-clamp-3 text-xs">{citation.text.slice(0, 120)}</p>
    </div>
  );
}

export function CitationMark({
  items,
  messageId,
}: {
  /** One entry per cited source, DISPLAY numbers (sorted strip positions) ascending. */
  items: CitationMarkItem[];
  messageId: string;
}) {
  const { t } = useI18n();
  const tc = t.knowledge.chat;
  const label = items
    .map((item) => tc.sourceMarkAriaLabel(item.index, item.citation.doc_name))
    .join("; ");
  return (
    <HoverCard closeDelay={100} openDelay={300}>
      <HoverCardTrigger asChild>
        <button
          aria-label={label}
          className="text-muted-foreground/70 hover:bg-muted/60 hover:text-foreground mx-px inline-flex h-[1.4em] items-center justify-center rounded px-px align-super text-[0.3em] leading-none font-medium transition-colors"
          data-citation-mark={items.map((item) => item.index).join(",")}
          type="button"
          onClick={() => {
            const detail: CitationJumpDetail = {
              messageId,
              indices: items.map((item) => item.index),
            };
            window.dispatchEvent(new CustomEvent(KB_CITATION_JUMP_EVENT, { detail }));
          }}
        >
          {items.map((item) => item.index).join(",")}
        </button>
      </HoverCardTrigger>
      <HoverCardContent className="w-72">
        <div className="flex flex-col gap-2">
          {items.map((item) => (
            <CitationPreviewCard citation={item.citation} key={item.index} />
          ))}
        </div>
      </HoverCardContent>
    </HoverCard>
  );
}

/**
 * Build the markdown ``sup`` component override for one assistant message.
 * The rehype-citation-marks plugin emits ``<sup data-citation-index="n">``
 * (single) or ``<sup data-citation-indices="n1 n2">`` (whitespace-adjacent
 * run) where each ``n`` is the number the model wrote (the backend
 * citation_no — an internal handle, NEVER shown). The mark renders the
 * DISPLAY numbers: each source's 1-based position in the deduped,
 * citation_no-sorted strip, so the visible number space is continuous (1..N)
 * and matches the cards exactly (Perplexity-style). A group is shown as one
 * pill with its display numbers sorted ascending and deduped. Resolution per
 * number: (1) the source whose merged citation_nos contains ``n`` —
 * hybrid/graph overlap assigns one chunk several numbers, and the model may
 * cite any of them; (2) positional fallback for legacy sources without
 * citation_nos. A number nothing resolves falls back to a plain sup (raw
 * text, as before) so stale/foreign marks never crash; in a mixed group the
 * resolvable part still renders as a pill.
 */
export function createCitationSupRenderer(sources: KnowledgeCitation[], messageId: string) {
  return function CitationSupRenderer(props: ComponentProps<"sup">) {
    const record = props as Record<string, unknown>;
    const raws = parseCitedNumbers(
      record["data-citation-index"],
      record["data-citation-indices"],
    );
    if (raws.length === 0) {
      return <sup {...props} />;
    }
    const items: CitationMarkItem[] = [];
    const unresolved: number[] = [];
    for (const cited of raws) {
      let position = sources.findIndex((source) =>
        source.citation_nos?.includes(cited),
      );
      if (position < 0 && sources.every((source) => !source.citation_nos)) {
        // Legacy payloads carry no citation numbers at all — positional mapping.
        position = cited - 1 < sources.length ? cited - 1 : -1;
      }
      const citation = position >= 0 ? sources[position] : undefined;
      if (citation) {
        const index = position + 1;
        if (!items.some((item) => item.index === index)) {
          items.push({ citation, index });
        }
      } else if (!unresolved.includes(cited)) {
        unresolved.push(cited);
      }
    }
    if (items.length === 0) {
      return <sup {...props} />;
    }
    items.sort((a, b) => a.index - b.index);
    return (
      <>
        <CitationMark items={items} messageId={messageId} />
        {unresolved.map((cited) => (
          <sup key={cited}>{cited}</sup>
        ))}
      </>
    );
  };
}

function parseCitedNumbers(single: unknown, multi: unknown): number[] {
  const out: number[] = [];
  const push = (value: unknown) => {
    const n =
      typeof value === "number"
        ? value
        : typeof value === "string"
          ? Number(value)
          : NaN;
    if (Number.isInteger(n) && n >= 1 && !out.includes(n)) {
      out.push(n);
    }
  };
  if (typeof multi === "string") {
    for (const part of multi.split(/\s+/)) {
      push(part);
    }
  } else {
    push(single);
  }
  return out;
}
