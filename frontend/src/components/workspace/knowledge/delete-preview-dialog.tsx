"use client";

import { AlertTriangle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
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
import type { DeletePreviewResponse } from "@/core/knowledge/types";

/**
 * Delete impact preview dialog (Phase-3 Batch-1 P5): shows orphaned entities,
 * affected entities, and relation deletions before confirming chunk deletion.
 */
export function DeletePreviewDialog({
  open,
  onOpenChange,
  preview,
  onConfirm,
  isDeleting,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  preview: DeletePreviewResponse | null;
  onConfirm: () => void;
  isDeleting: boolean;
}) {
  const { t } = useI18n();
  const tc = t.knowledge.chunkDrawer;

  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-yellow-600" />
            {tc.deletePreviewTitle}
          </DialogTitle>
          <DialogDescription>{tc.deleteWarning}</DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4 py-4">
          {preview && preview.orphaned_entities.length > 0 && (
            <div className="flex flex-col gap-2">
              <h4 className="text-sm font-medium text-red-600">
                {tc.orphanedEntities} ({preview.orphaned_entities.length})
              </h4>
              <div className="flex flex-wrap gap-1">
                {preview.orphaned_entities.map((entity) => (
                  <Badge className="border-red-300 bg-red-50 text-red-700" key={entity} variant="outline">
                    {entity}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          {preview && preview.affected_entities.length > 0 && (
            <div className="flex flex-col gap-2">
              <h4 className="text-sm font-medium text-yellow-600">
                {tc.affectedEntities} ({preview.affected_entities.length})
              </h4>
              <div className="flex flex-wrap gap-1">
                {preview.affected_entities.map((entity) => (
                  <Badge
                    className="border-yellow-300 bg-yellow-50 text-yellow-700"
                    key={entity}
                    variant="outline"
                  >
                    {entity}
                  </Badge>
                ))}
              </div>
            </div>
          )}

          {preview && preview.relation_deletions.length > 0 && (
            <div className="flex flex-col gap-2">
              <h4 className="text-muted-foreground text-sm font-medium">
                {tc.relationDeletions}: {preview.relation_deletions.length}
              </h4>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button disabled={isDeleting} onClick={() => onOpenChange(false)} variant="outline">
            {tc.cancel}
          </Button>
          <Button disabled={isDeleting} onClick={onConfirm} variant="destructive">
            {tc.confirmDelete}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
