"use client";

/**
 * B′ 锚定拦截红块（2026-10-05）：三个入题面共用的内联机器证据块——缺失
 * 术语、建议锚与命中计数（hits/best_hits 作 `1/3` 形），以及覆盖确认钮
 * （「仍要入库/仍要接受」，warning 色）。missing_chunk 不可覆盖，不渲染
 * 确认钮；其余错误不走本块（toast 旧路径）。
 */
import { Button } from "@/components/ui/button";
import { useI18n } from "@/core/i18n/hooks";
import type { AnchorBlockDetail } from "@/core/knowledge/types";
import { cn } from "@/lib/utils";

export interface AnchorBlockNoticeProps {
  detail: AnchorBlockDetail;
  /** 覆盖确认钮文案（缺省「仍要入库」；合成审核传「仍要接受」）。 */
  confirmLabel?: string;
  /** 缺省即不渲染确认钮（missing_chunk 等不可覆盖场景只传 detail）。 */
  onConfirm?: () => void;
  confirming?: boolean;
}

export function AnchorBlockNotice({ detail, confirmLabel, onConfirm, confirming = false }: AnchorBlockNoticeProps) {
  const { t } = useI18n();
  const tk = t.knowledge.eval.anchorBlock;
  // missing_chunk（锚定切片已不存在）不可被 anchor_ack 覆盖，无确认钮。
  const canConfirm = detail.reason !== "missing_chunk" && onConfirm !== undefined;
  const hitsLine = `${tk.hits} ${detail.hits}/${detail.best_hits}`;

  return (
    <div
      className={cn(
        "border-destructive/40 bg-destructive/10 text-destructive",
        "flex flex-col gap-1.5 rounded-md border p-2.5 text-xs",
      )}
      role="alert"
    >
      <p className="font-medium">{detail.reason === "missing_chunk" ? tk.missing : tk.title}</p>
      {detail.miss_terms.length > 0 && (
        <p>
          {tk.missTerms}: {detail.miss_terms.join(" ")}
        </p>
      )}
      <p>{detail.suggested_chunk !== null ? `${tk.suggest} ${detail.suggested_chunk}（${hitsLine}）` : hitsLine}</p>
      {canConfirm && (
        <div>
          <Button
            className="border-amber-500/40 bg-amber-500/15 text-amber-700 hover:bg-amber-500/25 hover:text-amber-700 dark:text-amber-500 dark:hover:text-amber-500"
            disabled={confirming}
            onClick={onConfirm}
            size="sm"
            variant="outline"
          >
            {confirmLabel ?? tk.confirmSave}
          </Button>
        </div>
      )}
    </div>
  );
}
