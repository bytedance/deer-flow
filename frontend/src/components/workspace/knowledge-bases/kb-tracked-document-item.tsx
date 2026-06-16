"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FileTextIcon, RefreshCwIcon } from "@/components/ui/icons";
import { useI18n } from "@/core/i18n/hooks";
import { useDocumentIndexStatus } from "@/core/knowledge-base";

export function classifyIndexState(
  indexStatus: { data?: { index_status?: string }; isPending: boolean },
): { isIndexing: boolean; isTerminal: boolean; status: string | undefined } {
  const status = indexStatus.data?.index_status;
  return {
    isIndexing:
      status === "pending" || status === "indexing" || indexStatus.isPending,
    isTerminal: status === "indexed" || status === "failed",
    status,
  };
}

export const __test_only = { classifyIndexState };

interface TrackedDocumentItemProps {
  kbId: string;
  docId: string;
  title: string;
  fileName: string;
  onDismiss: (docId: string) => void;
}

export function TrackedDocumentItem({
  kbId,
  docId,
  title,
  fileName,
  onDismiss,
}: TrackedDocumentItemProps) {
  const { t } = useI18n();
  const indexStatus = useDocumentIndexStatus(kbId, docId);

  const { isIndexing, isTerminal, status } = classifyIndexState(indexStatus);

  return (
    <div className="bg-muted/50 flex flex-col gap-3 rounded-lg border p-4">
      <div className="flex items-center gap-2">
        <FileTextIcon className="text-muted-foreground h-4 w-4" />
        <span className="truncate text-sm font-medium">
          {title || fileName}
        </span>
      </div>

      {isIndexing && (
        <div className="text-muted-foreground flex items-center gap-2 text-sm">
          <RefreshCwIcon className="h-3.5 w-3.5 animate-spin" />
          <span>{t.knowledgeBase.indexingInProgress}</span>
        </div>
      )}

      {status === "indexed" && (
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="text-xs">
            {indexStatus.data?.chunk_count ?? 0} {t.knowledgeBase.chunks}
          </Badge>
          <span className="text-muted-foreground text-sm">
            {t.knowledgeBase.indexComplete}
          </span>
        </div>
      )}

      {status === "failed" && (
        <div className="flex flex-col gap-2">
          <div className="text-destructive text-sm font-medium">
            {t.knowledgeBase.indexFailed}
          </div>
          {indexStatus.data?.index_error && (
            <p className="text-destructive/80 text-xs">
              {indexStatus.data.index_error}
            </p>
          )}
        </div>
      )}

      {isTerminal && (
        <div className="flex justify-end">
          <Button size="sm" variant="outline" onClick={() => onDismiss(docId)}>
            {t.common.close}
          </Button>
        </div>
      )}
    </div>
  );
}
