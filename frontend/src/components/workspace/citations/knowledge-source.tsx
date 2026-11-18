"use client";

import type { Message } from "@langchain/langgraph-sdk";
import { BookOpenTextIcon } from "lucide-react";
import { createContext, useContext, useMemo, type ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { useI18n } from "@/core/i18n/hooks";
import {
  citedKnowledgeSources,
  collectKnowledgeSources,
  knowledgeSourceId,
  type KnowledgeSource,
} from "@/core/knowledge/sources";

const SourcesContext = createContext<ReadonlyMap<string, KnowledgeSource>>(
  new Map(),
);

export function KnowledgeSourcesProvider({
  messages,
  children,
}: {
  messages: readonly Message[];
  children: ReactNode;
}) {
  const sources = useMemo(() => collectKnowledgeSources(messages), [messages]);
  return (
    <SourcesContext.Provider value={sources}>
      {children}
    </SourcesContext.Provider>
  );
}

function SourceDialog({
  source,
  children,
}: {
  source: KnowledgeSource;
  children: ReactNode;
}) {
  const { t } = useI18n();
  return (
    <Dialog>
      <DialogTrigger asChild>
        <button
          type="button"
          className="text-left"
          aria-label={t.citations.viewKnowledgeSource(source.document_name)}
          onClick={(event) => event.stopPropagation()}
        >
          {children}
        </button>
      </DialogTrigger>
      <DialogContent className="max-h-[85dvh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="break-words">
            {source.document_name}
          </DialogTitle>
          <DialogDescription>
            {source.dataset_name}
            {source.pages.length > 0
              ? ` · ${t.citations.sourcePages(source.pages.join(", "))}`
              : ""}
          </DialogDescription>
        </DialogHeader>
        <p className="text-muted-foreground text-xs">
          {t.citations.retrievedExcerpt}
        </p>
        <blockquote className="border-primary/30 border-l-2 pl-4 text-sm leading-relaxed break-words whitespace-pre-wrap">
          {source.text}
        </blockquote>
        {source.truncated && (
          <p className="text-muted-foreground text-xs">
            {t.citations.excerptTruncated}
          </p>
        )}
      </DialogContent>
    </Dialog>
  );
}

export function KnowledgeCitationLink({
  href,
  children,
}: {
  href: string;
  children: ReactNode;
}) {
  const sources = useContext(SourcesContext);
  const { t } = useI18n();
  const id = knowledgeSourceId(href);
  const source = id ? sources.get(id) : undefined;
  if (!source)
    return (
      <span
        className="text-muted-foreground"
        title={t.citations.sourceUnavailable}
      >
        {children}
      </span>
    );
  return (
    <SourceDialog source={source}>
      <Badge
        variant="secondary"
        className="mx-0.5 cursor-pointer gap-1 rounded-full px-2 py-0.5 text-xs font-normal"
      >
        <BookOpenTextIcon className="size-3" />
        {children}
      </Badge>
    </SourceDialog>
  );
}

export function KnowledgeSourcesPanel({ content }: { content: string }) {
  const allSources = useContext(SourcesContext);
  const { t } = useI18n();
  const sources = useMemo(
    () => citedKnowledgeSources(content, allSources),
    [content, allSources],
  );
  if (sources.length === 0) return null;
  return (
    <details className="not-prose border-border/60 bg-muted/20 mt-2 rounded-md border text-xs">
      <summary className="text-muted-foreground cursor-pointer px-3 py-2">
        {t.citations.knowledgeSourcesSummary(sources.length)}
      </summary>
      <ul className="border-border/60 max-h-80 space-y-2 overflow-y-auto border-t p-3">
        {sources.map((source) => (
          <li key={source.id}>
            <SourceDialog source={source}>
              <span className="text-foreground block font-medium break-words">
                {source.document_name}
              </span>
              <span className="text-muted-foreground block break-words">
                {source.dataset_name}
              </span>
            </SourceDialog>
          </li>
        ))}
      </ul>
    </details>
  );
}
