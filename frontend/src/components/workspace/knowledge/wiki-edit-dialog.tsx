"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Textarea } from "@/components/ui/textarea";
import { useI18n } from "@/core/i18n/hooks";
import type { WikiEntryDetail } from "@/core/knowledge/types";

/**
 * Wiki entry dual-mode editor (Phase-3 Batch-1 P1).
 * - Main content area: editable, replaced on next LLM re-generation
 * - Supplement layer: persistent user annotations that survive re-generation
 */
export interface WikiEditDialogProps {
  entry: WikiEntryDetail | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (
    entryId: string,
    content: string,
    supplementContent: string | null,
  ) => Promise<void>;
}

export function WikiEditDialog({
  entry,
  open,
  onOpenChange,
  onSave,
}: WikiEditDialogProps) {
  const { t } = useI18n();
  const te = t.knowledge.wikiEdit;
  const [content, setContent] = useState(entry?.content ?? "");
  const [supplement, setSupplement] = useState(entry?.supplement_content ?? "");
  const [saving, setSaving] = useState(false);

  // Reset form when entry changes
  const entryId = entry?.id;
  const [prevEntryId, setPrevEntryId] = useState(entryId);
  if (entryId !== prevEntryId) {
    setPrevEntryId(entryId);
    setContent(entry?.content ?? "");
    setSupplement(entry?.supplement_content ?? "");
  }

  const handleSave = async () => {
    if (!entry) return;
    setSaving(true);
    try {
      await onSave(entry.id, content.trim(), supplement.trim() || null);
      onOpenChange(false);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[90vh] flex-col gap-4 overflow-hidden sm:max-w-[600px]">
        {/* 百科 Tab 容器同款 overlay 滚动条（2026-09-04）：DialogContent 改 flex col +
            overflow-hidden， header/正文/footer 整体经 ScrollArea 滚动。
            ⚠️ max-h 封顶必须加在 ScrollArea Root 上（2026-09-04 实测根因）：DialogContent
            高度是 auto 被 max-h-[90vh] 截帽的 indefinite 高度，沿 flex 链传递后 Viewport 的
            height:100% 回退 auto、被内容撑到全高 → 不是滚动容器 → 滚轮失效、滚动条不出现。
            Root 封顶后由原语 Viewport 的 max-h-inherit 继承，滚动容器才有界。
            90vh 减去对话框 chrome（p-6×2 + border ≈ 50px）再留 6px 余量，
            保证先触到的是这层封顶而不是 DialogContent 的 overflow-hidden 裁剪。
            -mx-6：Radix 滚动条绝对定位在 Root 右缘，Root 默认停在 p-6 内边距里会让
            滑块离窗缘差 24px；负右边距把 Root 伸进沟槽贴齐对话框右缘，
            内容包装的 px-6 保持文字缩进不变（滑块落在空白沟槽内不压字）。
            负左边距同理反向：ViewPort 内联 overflow-x:hidden 会裁掉焦点环外扩的
            3px（字段左缘与裁剪边零间隙时整条左环被吞），Root 向左伸进沟槽、
            内容包装 pl-6 补回缩进后，环落在裁剪盒内才画得全。 */}
        <ScrollArea
          className="-mx-6 max-h-[calc(90vh-3.5rem)] min-h-0 min-w-0 flex-1"
          scrollHideDelay={2000}
          type="scroll"
        >
          <div className="flex min-w-0 flex-col gap-4 px-6">
            <DialogHeader>
              <DialogTitle>{te.title}</DialogTitle>
              <DialogDescription>{te.description}</DialogDescription>
            </DialogHeader>

            {/* field-sizing-content 的 textarea 会把内容宽度沿 grid/flex item 链
            向上传递撑宽对话框——链上每层容器 min-w-0 阻断，宽度固定后
            长行自然软换行（横向滚动条随之消失）。 */}
            <div className="flex min-w-0 flex-col gap-4 py-4">
              {/* Main content area */}
              <div className="min-w-0 space-y-2">
                <Label htmlFor="wiki-main-content">{te.mainContentLabel}</Label>
                <Textarea
                  id="wiki-main-content"
                  className="min-h-[200px] resize-y font-mono text-sm"
                  placeholder={te.mainContentPlaceholder}
                  value={content}
                  onChange={(e) => setContent(e.target.value)}
                />
                <p className="text-muted-foreground text-xs">
                  {te.mainContentHint}
                </p>
              </div>

              {/* Supplement layer */}
              <div className="min-w-0 space-y-2 border-t pt-4">
                <Label htmlFor="wiki-supplement-content">
                  {te.supplementLabel}
                </Label>
                <Textarea
                  id="wiki-supplement-content"
                  className="min-h-[100px] resize-y text-sm"
                  placeholder={te.supplementPlaceholder}
                  value={supplement}
                  onChange={(e) => setSupplement(e.target.value)}
                />
                <p className="text-muted-foreground text-xs">
                  {te.supplementHint}
                </p>
              </div>

              {/* Audit metadata */}
              {entry?.updated_at && (
                <div className="text-muted-foreground space-y-1 border-t pt-4 text-xs">
                  <p>
                    {te.auditLastEdited}:{" "}
                    {new Date(entry.updated_at).toLocaleString()}
                  </p>
                </div>
              )}
            </div>

            <DialogFooter>
              <Button variant="outline" onClick={() => onOpenChange(false)}>
                {t.common.cancel}
              </Button>
              <Button disabled={!content.trim() || saving} onClick={handleSave}>
                {saving ? te.saving : te.save}
              </Button>
            </DialogFooter>
          </div>
        </ScrollArea>
      </DialogContent>
    </Dialog>
  );
}
