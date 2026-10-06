"use client";

/**
 * 完整评测确认对话框（2026-09-01 B 方案）：L1+L2 档成本远高于快速档
 * （每题 = 一次 Agent 实跑 + 独立 Judge 打分），触发前必须显式确认。
 * 确认回调由持有方（eval-tab / 题库批量栏）承接，本组件只管开关与文案。
 */
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

export interface EvalFullRunDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** 确认后触发完整档（调用方携带 layers="l1_l2" 与可选 question_ids）。 */
  onConfirm: () => void;
  /** 运行范围（2026-09-06）：所选题数；缺省=全库。弹窗据此标明范围，
      作为"只跑所选"的唯一提醒器（主按钮恒为档位名不附加后缀）。 */
  scopeCount?: number;
}

export function EvalFullRunDialog({ open, onOpenChange, onConfirm, scopeCount }: EvalFullRunDialogProps) {
  const { t } = useI18n();
  const tk = t.knowledge.eval.fullRun;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{tk.dialogTitle}</DialogTitle>
          <DialogDescription>
            {tk.dialogBody}
            {" "}
            {scopeCount !== undefined ? tk.dialogScopeSelected(scopeCount) : tk.dialogScopeAll}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button size="sm" variant="outline" onClick={() => onOpenChange(false)}>
            {tk.cancel}
          </Button>
          <Button
            size="sm"
            onClick={() => {
              onOpenChange(false);
              onConfirm();
            }}
          >
            {tk.confirm}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
