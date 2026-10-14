import { Badge } from "@/components/ui/badge";
import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from "@/components/ui/hover-card";
import type { RetrievalSource } from "@/core/citations/sources";
import { useI18n } from "@/core/i18n/hooks";

/** Local evidence is readable even when the provider returned no public URL. */
export function KnowledgeCitation({ source }: { source: RetrievalSource }) {
  return (
    <HoverCard closeDelay={0} openDelay={0}>
      <HoverCardTrigger asChild>
        <button
          type="button"
          className="inline-flex items-center"
          onClick={(event) => event.stopPropagation()}
        >
          <Badge
            variant="secondary"
            className="mx-0.5 rounded-full px-2 py-0.5 text-xs font-normal"
          >
            {source.title}
          </Badge>
        </button>
      </HoverCardTrigger>
      <HoverCardContent className="max-h-80 w-80 overflow-y-auto text-xs">
        <KnowledgeEvidence source={source} />
      </HoverCardContent>
    </HoverCard>
  );
}

export function KnowledgeEvidence({ source }: { source: RetrievalSource }) {
  const { t } = useI18n();
  return (
    <div className="space-y-2 break-words">
      <p className="font-medium">{source.title}</p>
      <p className="text-muted-foreground">
        {source.provider}
        {source.dataset_name ? ` / ${source.dataset_name}` : ""}
        {source.page
          ? ` · ${t.citations.sourcePages(String(source.page))}`
          : ""}
      </p>
      <blockquote className="border-border border-l-2 pl-2 whitespace-pre-wrap">
        {source.excerpt}
      </blockquote>
      {source.url && (
        <a
          href={source.url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-primary underline"
        >
          {source.url}
        </a>
      )}
    </div>
  );
}
