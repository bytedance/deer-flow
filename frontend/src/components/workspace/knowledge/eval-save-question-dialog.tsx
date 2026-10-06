"use client";

/**
 * 存为考题 dialog（2026-08-27 spec §7.1，plan Task 8）：召回面板勾选切片后
 * 的一键入题库——query 预填当前输入（可改），category 必填（shadcn Select，
 * 默认 fact），预期路径多路化（2026-08-28 §3，Task 9）：三项 Checkbox 组，
 * 默认勾选 = 勾选来源路径集合（混路即多勾，不再降级单路），至少一路才可
 * 提交；reference_answer 可选；relevant_chunk_ids = 勾选 chunk 集（造题主入
 * 口，题库随使用自然生长）。保存成功清勾选继续标注下一题——**不跳视图**。
 * B′ 锚定拦截（2026-10-05）：保存被锚定核验 422 拦下时按钮行下方出红块，
 * 原「保存」重提恒不带确认（盲双击不绕过），仅红块内「仍要入库」以
 * anchor_ack=true 覆盖（missing_chunk 不可覆盖，无确认钮）；改参考答案或
 * 勾选锚定集即清块，下一次保存重新机器核验。
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useI18n } from "@/core/i18n/hooks";
import { useAddEvalQuestion } from "@/core/knowledge/hooks";
import type { RecallPathName } from "@/core/knowledge/types";

import { AnchorBlockNotice } from "./anchor-block-notice";
import { toast } from "./kb-toast";
import { ScrollableTextarea } from "./scrollable-textarea";
import { useAnchorConfirm } from "./use-anchor-confirm";

export interface EvalSaveQuestionDialogProps {
  kbId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** 勾选的 chunk id 集（提交体 relevant_chunk_ids）。 */
  selectedChunkIds: string[];
  /** 勾选总数含人工卡片（2026-09-05：描述行计数；缺省回退 chunk 数）。 */
  selectionCount?: number;
  /** 默认勾选路径集合：勾选来源路径；混路即多勾（面板推导，2026-08-28）。 */
  defaultPaths: RecallPathName[];
  /** query 预填值（当前检索输入）。 */
  prefillQuery: string;
  /** 保存成功回调（面板清勾选）。 */
  onSaved?: () => void;
}

const CATEGORY_OPTIONS = ["fact", "relation", "concept", "global"] as const;
const PATH_OPTIONS = ["vector", "graph", "wiki"] as const;

/** B′ 拦截状态 key（单表单面一个）。 */
const ANCHOR_KEY = "form";

export function EvalSaveQuestionDialog({
  kbId,
  open,
  onOpenChange,
  selectedChunkIds,
  selectionCount,
  defaultPaths,
  prefillQuery,
  onSaved,
}: EvalSaveQuestionDialogProps) {
  const { t } = useI18n();
  const stk = t.knowledge.recallTest.saveAsQuestion;
  const etk = t.knowledge.eval;
  const addMutation = useAddEvalQuestion(kbId);
  // B′ 锚定拦截（2026-10-05）：见文件头。
  const anchor = useAnchorConfirm();
  const anchorBlock = anchor.blockFor(ANCHOR_KEY);
  const { clear } = anchor;

  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<(typeof CATEGORY_OPTIONS)[number]>("fact");
  const [expectedPaths, setExpectedPaths] = useState<RecallPathName[]>(defaultPaths);
  const [referenceAnswer, setReferenceAnswer] = useState("");

  // 每次打开重置为预填值与默认勾选（上一题的选择不残留）
  useEffect(() => {
    if (open) {
      setQuery(prefillQuery);
      setCategory("fact");
      setExpectedPaths(defaultPaths);
      setReferenceAnswer("");
      clear(ANCHOR_KEY);
    }
  }, [open, prefillQuery, defaultPaths, clear]);

  // B′：勾选锚定集（内容级比较）变化即清红块——重新机器核验。父层重渲染
  // 不换内容不清块（勾选数组常为派生新引用）。
  const selectionKey = selectedChunkIds.join("\n");
  useEffect(() => {
    clear(ANCHOR_KEY);
  }, [selectionKey, clear]);

  const togglePath = (path: RecallPathName) =>
    setExpectedPaths((current) => (current.includes(path) ? current.filter((item) => item !== path) : [...current, path]));

  // 至少勾一路（后端 min_length=1）+ query 非空。锚定集可为空（2026-09-05）：
  // 纯人工卡片勾选产出无锚定题——题库既有降级语义（仅参与路径判定）。
  const canSubmit = query.trim().length > 0 && expectedPaths.length > 0;

  // 提交体共用（首击与红块确认仅 anchor_ack 不同）：原按钮恒不带确认重提。
  const submitQuestion = (ack: boolean) =>
    addMutation.mutateAsync({
      query: query.trim(),
      category,
      // 勾选顺序即提交顺序；后端去重保序（§3）。
      expected_paths: expectedPaths,
      relevant_chunk_ids: selectedChunkIds,
      reference_answer: referenceAnswer.trim() ? referenceAnswer.trim() : null,
      anchor_ack: ack,
    });

  const handleSubmit = async () => {
    if (!canSubmit) return;
    try {
      const saved = await anchor.submit(ANCHOR_KEY, submitQuestion);
      if (!saved) return;
      toast.success(stk.savedToast);
      onSaved?.();
      onOpenChange(false);
    } catch (error) {
      toast.error(error instanceof Error && error.message ? error.message : stk.saveFailed);
    }
  };

  // 红块内「仍要入库」：anchor_ack=true 覆盖词条级拦截后走正常保存收尾。
  const handleConfirm = async () => {
    try {
      const saved = await anchor.confirm(ANCHOR_KEY, submitQuestion);
      if (!saved) return;
      toast.success(stk.savedToast);
      onSaved?.();
      onOpenChange(false);
    } catch (error) {
      toast.error(error instanceof Error && error.message ? error.message : stk.saveFailed);
    }
  };

  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{stk.button}</DialogTitle>
          <DialogDescription>{stk.selectedCount(selectionCount ?? selectedChunkIds.length)}</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <span className="text-sm font-medium">{stk.queryLabel}</span>
            <ScrollableTextarea
              aria-label={stk.queryLabel}
              onChange={(event) => setQuery(event.target.value)}
              value={query}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-1">
              <span className="text-sm font-medium">{stk.categoryLabel}</span>
              <Select onValueChange={(value) => setCategory(value as typeof category)} value={category}>
                <SelectTrigger aria-label={stk.categoryLabel} className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {CATEGORY_OPTIONS.map((value) => (
                    <SelectItem key={value} value={value}>
                      {etk.category[value]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-sm font-medium">{stk.expectedPathsLabel}</span>
              {/* 多路 Checkbox 组（2026-08-28 §3）：任一路承担即对，至少勾一路。 */}
              <div className="flex items-center gap-3 pt-1.5">
                {PATH_OPTIONS.map((path) => (
                  <label key={path} className="flex cursor-pointer items-center gap-1.5 text-sm">
                    <Checkbox checked={expectedPaths.includes(path)} onCheckedChange={() => togglePath(path)} />
                    {path}
                  </label>
                ))}
              </div>
            </div>
          </div>
          {/* 锚定辅助定位文案（2026-08-28 §5/§7）：勾选集即锚定集。 */}
          <p className="text-muted-foreground text-xs">{stk.anchorHint}</p>
          <div className="flex flex-col gap-1">
            <span className="text-sm font-medium">{stk.referenceAnswerLabel}</span>
            <ScrollableTextarea
              aria-label={stk.referenceAnswerLabel}
              onChange={(event) => {
                setReferenceAnswer(event.target.value);
                // B′：参考答案是锚定核验输入，改动即清红块（重新机器核验）。
                anchor.clear(ANCHOR_KEY);
              }}
              value={referenceAnswer}
            />
          </div>
        </div>
        <DialogFooter>
          <Button onClick={() => onOpenChange(false)} variant="outline">
            {stk.cancel}
          </Button>
          <Button disabled={!canSubmit || addMutation.isPending} onClick={handleSubmit}>
            {stk.submit}
          </Button>
        </DialogFooter>
        {/* B′ 红块：按钮行正下方（同表单内联错误位，非弹窗）；原「保存」保留原
            文案与无确认重提语义，仅红块内「仍要入库」携 anchor_ack=true。 */}
        {anchorBlock !== null && (
          <AnchorBlockNotice
            confirmLabel={etk.anchorBlock.confirmSave}
            confirming={addMutation.isPending}
            detail={anchorBlock}
            onConfirm={() => void handleConfirm()}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}
