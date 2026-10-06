"use client";

/**
 * 添加考题 dialog（2026-08-27 spec §4.4，plan Task 6）：简化表单——
 * query + category + 至少一路预期路径必填、reference_answer 可选；分类默认取
 * 第一项无空占位项（2026-08-28 用户反馈），预期路径多路化（2026-08-28 §3，
 * Task 9）：Checkbox 组，默认仅勾 vector。不暴露 relevant_chunk_ids /
 * relevant_entities 输入：手填 chunk id 痛苦且无意义，锚定的正确来源是召回面
 * 板「存为考题」（§7.1）；提交体不含锚定键，后端补空数组即无锚定题（Layer 1 仅参与
 * 路径判定）。编辑不支持（§4.2 规则 5）。
 * B′ 锚定拦截（2026-10-05）：提交被锚定核验 422 拦下时按钮行下方出红块，
 * 原「添加」重提恒不带确认（盲双击不绕过），仅红块内「仍要入库」以
 * anchor_ack=true 覆盖（missing_chunk 不可覆盖，无确认钮）；改参考答案即
 * 清块，下一次保存重新机器核验。本 dialog 无锚定输入，生产里不会触发，仍
 * 按同契约接线（测试模拟 422）。
 */
import { Info } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useI18n } from "@/core/i18n/hooks";
import { useAddEvalQuestion } from "@/core/knowledge/hooks";
import type { RecallPathName } from "@/core/knowledge/types";

import { AnchorBlockNotice } from "./anchor-block-notice";
import { toast } from "./kb-toast";
import { ScrollableTextarea } from "./scrollable-textarea";
import { useAnchorConfirm } from "./use-anchor-confirm";

export interface EvalAddQuestionDialogProps {
  kbId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const CATEGORY_OPTIONS = ["fact", "relation", "concept", "global"] as const;
const PATH_OPTIONS = ["vector", "graph", "wiki"] as const;

/** B′ 拦截状态 key（单表单面一个）。 */
const ANCHOR_KEY = "form";

export function EvalAddQuestionDialog({ kbId, open, onOpenChange }: EvalAddQuestionDialogProps) {
  const { t } = useI18n();
  const etk = t.knowledge.eval;
  const dtk = etk.questions.addDialog;
  const addMutation = useAddEvalQuestion(kbId);
  // B′ 锚定拦截（2026-10-05）：见文件头。
  const anchor = useAnchorConfirm();
  const anchorBlock = anchor.blockFor(ANCHOR_KEY);

  // 分类必填，默认取第一项——不设空占位项（2026-08-28 用户反馈：
  // 下拉框里的空行观感差且易误选）。预期路径 Checkbox 组，默认仅勾 vector。
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<(typeof CATEGORY_OPTIONS)[number]>("fact");
  const [expectedPaths, setExpectedPaths] = useState<RecallPathName[]>(["vector"]);
  const [referenceAnswer, setReferenceAnswer] = useState("");

  const togglePath = (path: RecallPathName) =>
    setExpectedPaths((current) => (current.includes(path) ? current.filter((item) => item !== path) : [...current, path]));

  // 至少勾一路（后端 min_length=1）。
  const canSubmit = query.trim().length > 0 && expectedPaths.length > 0;

  const handleClose = (next: boolean) => {
    if (!next) {
      setQuery("");
      setCategory("fact");
      setExpectedPaths(["vector"]);
      setReferenceAnswer("");
      anchor.clear(ANCHOR_KEY);
    }
    onOpenChange(next);
  };

  // 提交体共用（首击与红块确认仅 anchor_ack 不同）：原按钮恒不带确认重提。
  const submitQuestion = (ack: boolean) =>
    addMutation.mutateAsync({
      query: query.trim(),
      category,
      expected_paths: expectedPaths,
      // 锚定键不出现在提交体（测试钉死）；无参考答案显式 null
      reference_answer: referenceAnswer.trim() ? referenceAnswer.trim() : null,
      anchor_ack: ack,
    });

  const handleSubmit = async () => {
    if (!canSubmit) return;
    try {
      const saved = await anchor.submit(ANCHOR_KEY, submitQuestion);
      if (!saved) return;
      toast.success(etk.questions.addedToast);
      handleClose(false);
    } catch (error) {
      toast.error(error instanceof Error && error.message ? error.message : etk.questions.saveFailed);
    }
  };

  // 红块内「仍要入库」：anchor_ack=true 覆盖词条级拦截后走正常保存收尾。
  const handleConfirm = async () => {
    try {
      const saved = await anchor.confirm(ANCHOR_KEY, submitQuestion);
      if (!saved) return;
      toast.success(etk.questions.addedToast);
      handleClose(false);
    } catch (error) {
      toast.error(error instanceof Error && error.message ? error.message : etk.questions.saveFailed);
    }
  };

  return (
    <Dialog onOpenChange={handleClose} open={open}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{dtk.title}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <label className="flex flex-col gap-1">
            <span className="text-sm font-medium">{dtk.queryLabel}</span>
            <ScrollableTextarea
              aria-label={dtk.queryLabel}
              onChange={(event) => setQuery(event.target.value)}
              value={query}
            />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-1">
              <span className="text-sm font-medium">{dtk.categoryLabel}</span>
              {/* shadcn Select（agent-settings-dialog 先例）——样式与选项悬停态与全站一致；默认首项无空占位（2026-08-28 反馈） */}
              <Select onValueChange={(value) => setCategory(value as typeof category)} value={category}>
                <SelectTrigger aria-label={dtk.categoryLabel} className="w-full">
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
              <span className="text-sm font-medium">{dtk.expectedPathLabel}</span>
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
          <label className="flex flex-col gap-1">
            <span className="text-sm font-medium">{dtk.referenceAnswerLabel}</span>
            <ScrollableTextarea
              aria-label={dtk.referenceAnswerLabel}
              onChange={(event) => {
                setReferenceAnswer(event.target.value);
                // B′：参考答案是锚定核验输入，改动即清红块（重新机器核验）。
                anchor.clear(ANCHOR_KEY);
              }}
              value={referenceAnswer}
            />
          </label>
          {/* ⓘ 说明：无锚定题的评测口径（不长篇 inline，spec §4.4） */}
          <p className="text-muted-foreground flex items-center gap-1 text-xs">
            <Tooltip>
              <TooltipTrigger asChild>
                <Info aria-label={dtk.unanchoredNote} className="size-3.5 shrink-0" />
              </TooltipTrigger>
              <TooltipContent className="max-w-60 text-pretty">{dtk.unanchoredNote}</TooltipContent>
            </Tooltip>
            {dtk.unanchoredNote}
          </p>
        </div>
        <DialogFooter>
          <Button onClick={() => handleClose(false)} variant="outline">
            {dtk.cancel}
          </Button>
          <Button disabled={!canSubmit || addMutation.isPending} onClick={handleSubmit}>
            {dtk.submit}
          </Button>
        </DialogFooter>
        {/* B′ 红块：按钮行正下方（同表单内联错误位，非弹窗）；原「添加」保留原
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
