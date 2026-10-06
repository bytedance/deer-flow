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

/**
 * Rebuild-index confirm dialog (spec 2026-09-14 §5 / P4). A rebuild re-embeds every live
 * chunk of the chosen library and can run for a while, so this confirms first and — since
 * the settings page carries no library identity of its own — names the target explicitly.
 */
export function ReindexDialog({
  open,
  onOpenChange,
  kbName,
  onConfirm,
  pending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  kbName: string;
  onConfirm: () => void;
  pending: boolean;
}) {
  const { t } = useI18n();
  const F = t.settings.functionalModels;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle>{F.reindexConfirmTitle}</DialogTitle>
          <DialogDescription>
            {F.reindexConfirmDescription}{" "}
            <span className="text-foreground font-medium">{kbName}</span>
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t.common.cancel}
          </Button>
          <Button disabled={pending} onClick={onConfirm}>
            {F.reindexConfirmAction}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
