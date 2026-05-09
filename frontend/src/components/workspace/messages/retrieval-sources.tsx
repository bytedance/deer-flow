"use client";

import type { Message } from "@langchain/langgraph-sdk";
import { BookOpenIcon, ChevronDownIcon } from "lucide-react";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import {
  extractRetrievalTrace,
  type RetrievalSource,
} from "@/core/messages/utils";
import { cn } from "@/lib/utils";

export function RetrievalSources({ messages }: { messages: Message[] }) {
  const sources = useMemo(() => extractRetrievalTrace(messages), [messages]);
  const [expanded, setExpanded] = useState(false);

  if (!sources || sources.length === 0) return null;

  return (
    <div className="mt-2 w-full">
      <button
        type="button"
        className="text-muted-foreground hover:text-foreground flex items-center gap-1.5 text-xs transition-colors"
        onClick={() => setExpanded((v) => !v)}
      >
        <BookOpenIcon className="h-3.5 w-3.5" />
        <span>
          {sources.length} knowledge source{sources.length > 1 ? "s" : ""}
        </span>
        <ChevronDownIcon
          className={cn(
            "h-3 w-3 transition-transform",
            expanded && "rotate-180",
          )}
        />
      </button>
      {expanded && (
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {sources.map((source) => (
            <SourceBadge key={`${source.kb_id}:${source.doc_title}`} source={source} />
          ))}
        </div>
      )}
    </div>
  );
}

function SourceBadge({ source }: { source: RetrievalSource }) {
  return (
    <Badge variant="secondary" className="gap-1 text-xs font-normal">
      <span className="max-w-32 truncate">{source.kb_name}</span>
      <span className="text-muted-foreground">·</span>
      <span className="max-w-40 truncate">{source.doc_title}</span>
    </Badge>
  );
}
