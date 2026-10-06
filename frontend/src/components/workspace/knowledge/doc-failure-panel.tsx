"use client";

import { CircleAlert, RotateCcw, X } from "lucide-react";
import { useState } from "react";

import { ScrollArea } from "@/components/ui/scroll-area";
import { useI18n } from "@/core/i18n/hooks";
import type { DocFailureEntry } from "@/core/knowledge/use-doc-failure-notifier";

/**
 * In-tab failure notification panel (2026-08-31): document errors no longer
 * ride the global sonner toast (viewport-level — it can never stay inside
 * the tab), so this self-drawn card lives at the bottom-right corner of the
 * document tab. Background replicates the global toast verbatim (pure white
 * in light / pure black in dark theme, floating on shadow). Layout is
 * title + description two-line: long file names truncate on their own line.
 * Interaction contract (user-finalized): ✕ on the right; hovering the BODY
 * expands the folded list while hovering ✕ never does; header ✕ dismisses
 * all, per-row ✕ dismisses one; retryable entries carry a retry button;
 * entries persist until manually dismissed — state-driven, no timer.
 */

/** 紧凑重试按钮（展开行与单条卡共用）。 */
function RetryButton({
  label,
  onClick,
}: {
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      className="border-border hover:bg-muted flex h-6 shrink-0 items-center gap-1 rounded border px-2 text-xs transition-colors"
      onClick={onClick}
      type="button"
    >
      <RotateCcw className="size-3" />
      {label}
    </button>
  );
}

/** 条目正文：文件名独占一行截断，原因次级色截断（两行制）。 */
function EntryBody({ entry }: { entry: DocFailureEntry }) {
  return (
    <div className="min-w-0 flex-1">
      <p className="truncate text-xs font-medium">{entry.name}</p>
      <p className="text-muted-foreground truncate text-xs">{entry.reason}</p>
    </div>
  );
}

export function DocFailurePanel({
  failures,
  onDismiss,
  onDismissAll,
  onRetry,
}: {
  failures: DocFailureEntry[];
  onDismiss: (key: string) => void;
  onDismissAll: () => void;
  onRetry?: (key: string) => void;
}) {
  const { t } = useI18n();
  const tk = t.knowledge.docErrors;
  const [expanded, setExpanded] = useState(false);
  if (failures.length === 0) return null;
  const multiple = failures.length > 1;
  const first = failures[0]!;
  const closeClass =
    "hover:bg-muted text-muted-foreground hover:text-foreground shrink-0 rounded p-1 transition-colors";
  return (
    <div
      className="border-border/60 absolute right-3 bottom-3 z-20 w-80 max-w-[calc(100%-1.5rem)] overflow-hidden rounded-lg border bg-white shadow-lg dark:bg-black"
      data-testid="doc-failure-panel"
      onMouseLeave={() => setExpanded(false)}
    >
      <div className="flex items-center gap-1.5 py-2 pr-2 pl-3">
        {/* 展开感应区只覆盖图标+文字主体，✕ 是其兄弟节点——
            悬停总关闭按钮永远不会展开明细（用户反馈第 4 条）。 */}
        <div
          className="flex min-w-0 flex-1 items-center gap-2"
          data-testid="doc-failure-summary"
          onMouseEnter={() => {
            if (multiple) setExpanded(true);
          }}
        >
          <CircleAlert className="text-destructive size-4 shrink-0" />
          {multiple ? (
            <span className="min-w-0 flex-1 truncate text-xs">{`${tk.toastTitle}（${failures.length}）`}</span>
          ) : (
            <EntryBody entry={first} />
          )}
        </div>
        {/* 单条且可重试：重试与关闭并排右侧；上传即拒类无行可重试，只有关闭 */}
        {!multiple && first.retryable && onRetry && (
          <RetryButton
            label={t.knowledge.retryDocument}
            onClick={() => onRetry(first.key)}
          />
        )}
        <button
          aria-label={tk.dismissAll}
          className={closeClass}
          onClick={onDismissAll}
          type="button"
        >
          <X className="size-3.5" />
        </button>
      </div>
      {/* 百科 Tab 容器同款 overlay 滚动条（2026-09-04）：失败清单 max-h 内滚改 ScrollArea。 */}
      {multiple && expanded && (
        <ScrollArea
          className="border-border max-h-40 border-t"
          scrollHideDelay={2000}
          type="scroll"
        >
          <ul>
            {failures.map((entry) => (
              <li
                className="flex items-center gap-1.5 py-1.5 pr-2 pl-3"
                key={entry.key}
              >
                <EntryBody entry={entry} />
                {entry.retryable && onRetry && (
                  <RetryButton
                    label={t.knowledge.retryDocument}
                    onClick={() => onRetry(entry.key)}
                  />
                )}
                <button
                  aria-label={tk.dismiss}
                  className={closeClass}
                  onClick={() => onDismiss(entry.key)}
                  type="button"
                >
                  <X className="size-3.5" />
                </button>
              </li>
            ))}
          </ul>
        </ScrollArea>
      )}
    </div>
  );
}
