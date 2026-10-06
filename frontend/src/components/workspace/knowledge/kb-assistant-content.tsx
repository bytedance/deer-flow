"use client";

import { useMemo } from "react";

import { MarkdownContent } from "@/components/workspace/messages/markdown-content";
import { rehypeCitationMarks } from "@/core/knowledge/rehype-citation-marks";
import type { KnowledgeCitation } from "@/core/knowledge/types";

import { createCitationSupRenderer } from "./citation-mark";

/**
 * Assistant message body for the knowledge chat panel (phase-2 batch-1, P2).
 * Plain MarkdownContent while streaming; once the stream settles the
 * rehype-citation-marks plugin rewrites ``[n]`` into superscript marks
 * backed by this message's own sources (deferred rendering — a half-typed
 * ``[`` mid-stream never flickers).
 */
export function KbAssistantContent({
  content,
  isLoading,
  sources,
  messageId,
}: {
  content: string;
  isLoading: boolean;
  sources: KnowledgeCitation[];
  messageId: string;
}) {
  const supRenderer = useMemo(() => createCitationSupRenderer(sources, messageId), [sources, messageId]);
  return (
    <MarkdownContent
      components={{ sup: supRenderer }}
      content={content}
      isLoading={isLoading}
      rehypePlugins={isLoading ? [] : [rehypeCitationMarks]}
    />
  );
}
