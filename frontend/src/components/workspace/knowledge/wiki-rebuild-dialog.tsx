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
 * Wiki full-rebuild confirm dialog (shared, 2026-08-30): full mode rewrites
 * every eligible entry at high LLM cost, so both trigger sites — the library
 * header menu (middle-tabs) and the wiki tab's ⋯ menu — funnel through this
 * same cost-warning confirmation instead of duplicating the dialog JSX.
 */
export function WikiRebuildDialog({
  open,
  onOpenChange,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
}) {
  const { t } = useI18n();
  const tk = t.knowledge;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle>{tk.rebuildWikiConfirmTitle}</DialogTitle>
          <DialogDescription>{tk.rebuildWikiConfirmDescription}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t.common.cancel}
          </Button>
          <Button onClick={onConfirm}>{tk.rebuildWikiConfirmAction}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
