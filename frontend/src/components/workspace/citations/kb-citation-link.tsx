import type { RetrievalSource } from "@/core/messages/utils";

import { Badge } from "@/components/ui/badge";
import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from "@/components/ui/hover-card";

export function KBCitationLink({
  href,
  children,
  sources,
}: {
  href: string;
  children: React.ReactNode;
  sources?: RetrievalSource[] | null;
}) {
  const kbId = href.replace("kb://", "");
  const source = sources?.find((s) => s.kb_id === kbId) ?? null;

  const badge = (
    <Badge
      variant="secondary"
      className="mx-0.5 inline-flex cursor-default gap-1 rounded-full bg-blue-100 px-2 py-0.5 text-xs font-normal text-blue-700 hover:bg-blue-200 dark:bg-blue-900/30 dark:text-blue-400 dark:hover:bg-blue-900/50"
    >
      {children}
    </Badge>
  );

  if (!source) {
    return <span className="inline-flex items-center">{badge}</span>;
  }

  return (
    <HoverCard closeDelay={0} openDelay={0}>
      <HoverCardTrigger asChild>
        <span className="inline-flex items-center">{badge}</span>
      </HoverCardTrigger>
      <HoverCardContent className="relative w-72 p-0">
        <div className="space-y-1.5 p-3">
          <h4 className="truncate text-sm leading-tight font-medium">
            {source.doc_title}
          </h4>
          <p className="text-muted-foreground truncate text-xs">
            {source.kb_name}
          </p>
          <p className="text-muted-foreground text-xs">
            Score: {source.score.toFixed(2)}
          </p>
        </div>
      </HoverCardContent>
    </HoverCard>
  );
}
