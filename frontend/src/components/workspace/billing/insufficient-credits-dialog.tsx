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

export function InsufficientCreditsDialog({
  open,
  availableCredits,
  requiredCredits,
  onOpenChange,
  onRecharge,
}: {
  open: boolean;
  availableCredits: number;
  requiredCredits: number;
  onOpenChange: (open: boolean) => void;
  onRecharge: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>积分不足</DialogTitle>
          <DialogDescription>
            当前可用 {availableCredits} 积分，本次任务至少需要 {requiredCredits}{" "}
            积分。充值后请重新发起任务。
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button onClick={onRecharge}>立即充值</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
