import { ArchiveRestore } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/core/i18n/hooks";
import { isThreadArchived } from "@/core/threads/utils";

import { useThreadArchiveAction } from "./use-thread-archive-action";

export function ThreadArchiveStatus({
  threadId,
  metadata,
}: {
  threadId: string;
  metadata?: Record<string, unknown> | null;
}) {
  const { t } = useI18n();
  const { setArchived, isPending } = useThreadArchiveAction();
  if (!isThreadArchived({ metadata: metadata ?? {} })) return null;
  return (
    <div
      className="flex shrink-0 items-center gap-1 text-xs"
      title={t.chats.archiveDescription}
    >
      <span className="text-muted-foreground hidden sm:inline">
        {t.chats.archivedChats}
      </span>
      <Button
        size="sm"
        variant="ghost"
        disabled={isPending}
        onClick={() => setArchived(threadId, false)}
        aria-label={t.chats.restoreChat}
      >
        <ArchiveRestore className="size-4" />
        <span className="hidden sm:inline">{t.chats.restoreChat}</span>
      </Button>
    </div>
  );
}
