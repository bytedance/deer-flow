"use client";

import { LoaderIcon, TableIcon } from "lucide-react";

import { ConversationEmptyState } from "@/components/ai-elements/conversation";
import { useTeableShareView } from "@/core/teable/hooks";
import { cn } from "@/lib/utils";

export function TableCanvas({
  className,
  tableId,
  tableName,
  embedUrl,
}: {
  className?: string;
  tableId: string | null;
  tableName: string | null;
  embedUrl: string | null;
}) {
  const {
    data: shareView,
    isLoading,
    error,
  } = useTeableShareView(embedUrl ? null : tableId);

  // Agent-generated embed URL takes priority over manual table selection
  const activeUrl = embedUrl ?? shareView?.embed_url ?? null;

  if (!tableId && !embedUrl) {
    return (
      <div
        className={cn("flex size-full items-center justify-center", className)}
      >
        <ConversationEmptyState
          icon={<TableIcon />}
          title="No table selected"
          description="Select a table from the list, or ask in the chat"
        />
      </div>
    );
  }

  if (!embedUrl && isLoading) {
    return (
      <div
        className={cn("flex size-full items-center justify-center", className)}
      >
        <LoaderIcon className="text-muted-foreground h-5 w-5 animate-spin" />
      </div>
    );
  }

  if (!activeUrl) {
    return (
      <div
        className={cn(
          "flex size-full items-center justify-center p-4",
          className,
        )}
      >
        <ConversationEmptyState
          icon={<TableIcon />}
          title="Failed to load view"
          description={error?.message ?? "Could not create shared view"}
        />
      </div>
    );
  }

  return (
    <div className={cn("flex size-full flex-col overflow-hidden", className)}>
      <header className="border-b px-3 py-2">
        <h3 className="text-sm font-medium">{tableName ?? "Table View"}</h3>
      </header>
      <div className="min-h-0 grow">
        <iframe
          className="size-full"
          src={activeUrl}
          title={tableName ?? "Teable View"}
          allow="clipboard-read; clipboard-write"
          style={{ border: "none" }}
        />
      </div>
    </div>
  );
}
