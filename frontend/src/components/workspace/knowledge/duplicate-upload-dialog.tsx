"use client";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useI18n } from "@/core/i18n/hooks";
import type { KnowledgeDocument } from "@/core/knowledge/types";

/** One queued duplicate decision awaiting the user's choice (Task 11). */
export interface PendingDuplicate {
  /** The file's original name as selected (the copy name is shown separately). */
  fileName: string;
  /** identical = same name + same hash; conflict = same name + different/unknown hash. */
  kind: "identical" | "conflict";
  /** The existing same-name document in the current KB. */
  doc: KnowledgeDocument;
  /** Pre-allocated copy name for the keep-both branch (`name (2).ext`). */
  copyName?: string;
}

export type DuplicateAction = "skip" | "copy" | "replace" | "cancel";

/**
 * Duplicate-upload confirm dialog (Task 11). Presentational — the page owns
 * the queue, hash computation, and the mutation ordering (replace = delete
 * first, then re-upload; copy = upload under the allocated copy name).
 */
export function DuplicateUploadDialog({
  pending,
  onResolve,
}: {
  pending: PendingDuplicate | null;
  onResolve: (action: DuplicateAction) => void;
}) {
  const { t } = useI18n();
  const tk = t.knowledge.duplicateUpload;

  return (
    <Dialog open={pending !== null} onOpenChange={(open) => !open && onResolve("cancel")}>
      <DialogContent className="sm:max-w-[425px]">
        {pending?.kind === "identical" && (
          <>
            <DialogHeader>
              <DialogTitle>{tk.identicalTitle}</DialogTitle>
              <DialogDescription>{tk.identicalDescription(pending.fileName)}</DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button variant="outline" onClick={() => onResolve("copy")}>
                {tk.keepCopy}
              </Button>
              <Button variant="default" onClick={() => onResolve("skip")}>
                {tk.skipUpload}
              </Button>
            </DialogFooter>
          </>
        )}
        {pending?.kind === "conflict" && (
          <>
            <DialogHeader>
              <DialogTitle>{tk.conflictTitle}</DialogTitle>
              <DialogDescription>
                {tk.conflictDescription(pending.fileName)}
                {pending.copyName ? ` ${tk.copyNamePreview(pending.copyName)}` : ""}
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button variant="outline" onClick={() => onResolve("cancel")}>
                {t.common.cancel}
              </Button>
              <Button variant="secondary" onClick={() => onResolve("copy")}>
                {tk.keepBoth}
              </Button>
              <Button variant="destructive" onClick={() => onResolve("replace")}>
                {tk.replaceOld}
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
