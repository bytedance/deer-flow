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
 * Width-change confirm (spec 2026-09-26 D5-7). Changing the width is not a field edit: the
 * save rebuilds *every* library into a new generation of collections before the new width
 * takes effect, which is minutes of work, so it asks first — and says what stays true while
 * it runs (the old vectors keep serving) and what happens if it fails (nothing changes).
 */
export function DimensionMigrationDialog({
  open,
  onOpenChange,
  onConfirm,
  pending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
  pending: boolean;
}) {
  const { t } = useI18n();
  const F = t.settings.functionalModels;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle>{F.dimensionConfirmTitle}</DialogTitle>
          <DialogDescription>{F.dimensionConfirmDescription}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t.common.cancel}
          </Button>
          <Button disabled={pending} onClick={onConfirm}>
            {F.dimensionConfirmAction}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
