"use client";

/**
 * 合成考题触发 dialog（2026-08-28 spec §6.1，plan Task 11）：一到多篇文档（
 * 联合出题，2026-09-02 路线二：多篇切片全局统一编号，可出跨文档题）+
 * 候选题数（1–10，默认 5）→ POST /eval/questions/synthesize（202 幂等）。
 * 文档清单只列已索引（ready）文档——后端对任一无切片文档回 409，前端预过滤
 * 减少误触发。enqueued → success toast 并关闭；already_running → info
 * toast 不关闭（用户可等当前一轮落完）。
 */
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useI18n } from "@/core/i18n/hooks";
import { useDocuments, useTriggerSynthesis } from "@/core/knowledge/hooks";

import { toast } from "./kb-toast";

export interface EvalSynthesisDialogProps {
  kbId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const COUNT_OPTIONS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10] as const;

export function EvalSynthesisDialog({
  kbId,
  open,
  onOpenChange,
}: EvalSynthesisDialogProps) {
  const { t } = useI18n();
  const stk = t.knowledge.eval.synthesize;
  const trigger = useTriggerSynthesis(kbId);
  // dialog 打开才拉文档列表（懒门控）；只列已索引文档（无切片必 409）。
  const documents = useDocuments(open ? kbId : null);
  const readyDocs = (documents.data ?? []).filter(
    (doc) => doc.status === "ready",
  );

  // 多选清单：勾选顺序即提交顺序（后端保序去重）。
  const [docIds, setDocIds] = useState<string[]>([]);
  const [count, setCount] = useState<number>(5);

  // 每次打开重置（上一轮选择不残留）。
  useEffect(() => {
    if (open) {
      setDocIds([]);
      setCount(5);
    }
  }, [open]);

  const toggle = (docId: string) => {
    setDocIds((prev) =>
      prev.includes(docId)
        ? prev.filter((id) => id !== docId)
        : [...prev, docId],
    );
  };

  const canSubmit = docIds.length > 0 && !trigger.isPending;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    try {
      const response = await trigger.mutateAsync({ doc_ids: docIds, count });
      if (response.status === "enqueued") {
        toast.success(stk.generating);
        onOpenChange(false);
      } else {
        toast.info(stk.generating);
      }
    } catch (error) {
      toast.error(
        error instanceof Error && error.message
          ? error.message
          : stk.triggerFailed,
      );
    }
  };

  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{stk.dialogTitle}</DialogTitle>
          <DialogDescription>{stk.docPlaceholder}</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <span className="text-sm font-medium">{stk.docLabel}</span>
            {/* 多选清单（行即复选目标）：点击行或复选框都能勾选，
                复选框 stopPropagation 防双触发抵消。 */}
            {/* 百科 Tab 容器同款 overlay 滚动条（2026-09-04）：多选清单 max-h 内滚改
                ScrollArea（type="scroll"、停 2s 淡出），取代原生 overflow-y-auto。 */}
            <ScrollArea
              aria-label={stk.docLabel}
              className="border-input max-h-44 rounded-md border"
              role="group"
              scrollHideDelay={2000}
              type="scroll"
            >
              <div className="flex flex-col gap-0.5 p-1">
                {readyDocs.map((doc) => (
                  <div
                    className="hover:bg-muted/60 flex cursor-pointer items-center gap-2 rounded px-2 py-1.5"
                    key={doc.id}
                    onClick={() => toggle(doc.id)}
                  >
                    <Checkbox
                      aria-label={doc.name}
                      checked={docIds.includes(doc.id)}
                      onCheckedChange={() => toggle(doc.id)}
                      onClick={(event) => event.stopPropagation()}
                    />
                    <span className="truncate text-sm">{doc.name}</span>
                  </div>
                ))}
                {readyDocs.length === 0 && (
                  <p className="text-muted-foreground px-2 py-1.5 text-xs">
                    {stk.empty}
                  </p>
                )}
              </div>
            </ScrollArea>
          </div>
          <div className="flex flex-col gap-1">
            <span className="text-sm font-medium">{stk.countLabel}</span>
            <Select
              onValueChange={(value) => setCount(Number(value))}
              value={String(count)}
            >
              <SelectTrigger
                aria-label={stk.countLabel}
                className="w-full sm:w-40"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {COUNT_OPTIONS.map((value) => (
                  <SelectItem key={value} value={String(value)}>
                    {value}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
        <DialogFooter>
          <Button onClick={() => onOpenChange(false)} variant="outline">
            {t.knowledge.eval.questions.addDialog.cancel}
          </Button>
          <Button disabled={!canSubmit} onClick={handleSubmit}>
            {stk.generate}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
