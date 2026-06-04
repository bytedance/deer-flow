"use client";

import { BookOpenIcon, Loader2Icon } from "@/components/ui/icons";
import { useCallback, useEffect, useMemo, useRef } from "react";

import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useI18n } from "@/core/i18n/hooks";
import { useKnowledgeBases } from "@/core/knowledge-base";
import type { KnowledgeBaseSelection } from "@/core/threads";
import { cn } from "@/lib/utils";

import { PromptInputButton } from "../ai-elements/prompt-input";

import { Tooltip } from "./tooltip";

interface KnowledgeBaseSelectorProps {
  selection: KnowledgeBaseSelection | undefined;
  onSelectionChange: (selection: KnowledgeBaseSelection) => void;
}

/**
 * Build a stable signature from the KB IDs.
 *
 * Why a signature instead of the array itself: TanStack Query returns a
 * fresh `knowledgeBases` array reference on every poll even when the
 * contents are identical, so depending on the array directly turns the
 * cleanup effect into a hot loop. Sorting + joining the IDs gives us a
 * primitive that only changes when the underlying KB set actually does.
 */
function knowledgeBaseIdSignature(kbs: { id: string }[]): string {
  return kbs
    .map((kb) => kb.id)
    .sort()
    .join("|");
}

/**
 * Strip selected_ids that no longer correspond to any visible KB.
 *
 * Returns either the original selection (when no change is needed — the
 * caller compares by reference to avoid pointless setState calls) or a
 * cleaned copy. When *all* selected IDs are gone, `enabled` is forced
 * to false so the next chat turn doesn't try to retrieve from an empty
 * set and silently produce zero results.
 */
function cleanSelection(
  selection: KnowledgeBaseSelection,
  validIds: Set<string>,
): KnowledgeBaseSelection {
  const filtered = selection.selected_ids.filter((id) => validIds.has(id));
  if (filtered.length === selection.selected_ids.length) {
    return selection;
  }
  return {
    enabled: filtered.length > 0,
    selected_ids: filtered,
  };
}

export function KnowledgeBaseSelector({
  selection,
  onSelectionChange,
}: KnowledgeBaseSelectorProps) {
  const { t } = useI18n();
  const { knowledgeBases, isLoading } = useKnowledgeBases();

  const enabled = selection?.enabled ?? false;
  const selectedIds = useMemo(
    () => new Set(selection?.selected_ids ?? []),
    [selection?.selected_ids],
  );

  // Hold the latest callback in a ref so the cleanup effect doesn't fire
  // every time the parent re-renders with a fresh inline `onSelectionChange`.
  // The parent's recommended shape is a `useCallback`-stable function, but
  // we don't trust it — the ref keeps us correct either way.
  const onSelectionChangeRef = useRef(onSelectionChange);
  useEffect(() => {
    onSelectionChangeRef.current = onSelectionChange;
  }, [onSelectionChange]);

  // Re-run cleanup whenever the visible KB set changes. The signature is a
  // primitive so React compares it by value — a fresh KB array with the
  // same IDs is a no-op. Compared with the previous `hasCleaned` ref:
  //   - this still re-runs when the user adds a new KB and an old stale
  //     selection becomes valid (or vice-versa) later in the session;
  //   - it can never live-lock because cleanSelection returns the same
  //     reference when no change is needed.
  const idSignature = useMemo(
    () => knowledgeBaseIdSignature(knowledgeBases),
    [knowledgeBases],
  );

  useEffect(() => {
    if (isLoading || !selection?.enabled) return;
    if (knowledgeBases.length === 0) return;

    const validIds = new Set(knowledgeBases.map((kb) => kb.id));
    const next = cleanSelection(selection, validIds);
    if (next !== selection) {
      onSelectionChangeRef.current(next);
    }
    // We deliberately omit `selection` from the deps so a fresh callback
    // identity from the parent doesn't refire cleanup. The `idSignature`
    // and `selection.selected_ids` are the only inputs cleanSelection
    // actually reads, plus the loading flag.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idSignature, selection?.selected_ids, selection?.enabled, isLoading]);

  const handleToggleKB = useCallback(
    (id: string) => {
      const next = new Set(selectedIds);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      const ids = Array.from(next);
      onSelectionChangeRef.current({
        enabled: ids.length > 0,
        selected_ids: ids,
      });
    },
    [selectedIds],
  );
  const selectedCount = selectedIds.size;

  if (knowledgeBases.length === 0 && !isLoading) {
    return null;
  }

  return (
    <DropdownMenu>
      <Tooltip content={t.inputBox.knowledgeBase}>
        <DropdownMenuTrigger asChild>
          <PromptInputButton
            className={cn("gap-1! px-2!", enabled && "text-accent-foreground")}
          >
            <BookOpenIcon className="size-3" />
            {enabled && selectedCount > 0 && (
              <span className="text-xs font-normal">{selectedCount}</span>
            )}
          </PromptInputButton>
        </DropdownMenuTrigger>
      </Tooltip>
      <DropdownMenuContent className="w-64" align="start">
        <DropdownMenuLabel className="text-muted-foreground text-xs">
          {t.inputBox.knowledgeBase}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {isLoading ? (
          <div className="flex items-center justify-center py-4">
            <Loader2Icon className="text-muted-foreground size-4 animate-spin" />
          </div>
        ) : (
          (() => {
            const mine = knowledgeBases.filter((kb) => kb.visibility === "private");
            const tenant = knowledgeBases.filter((kb) => kb.visibility === "tenant");
            const pub = knowledgeBases.filter((kb) => kb.visibility === "public");
            const groups = [
              { label: t.knowledgeBase.groupMine, items: mine },
              { label: t.knowledgeBase.groupTenant, items: tenant },
              { label: t.knowledgeBase.groupPublic, items: pub },
            ].filter((g) => g.items.length > 0);
            return groups.map((group, gi) => (
              <div key={group.label}>
                {gi > 0 && <DropdownMenuSeparator />}
                <DropdownMenuLabel className="text-muted-foreground text-xs">
                  {group.label}
                </DropdownMenuLabel>
                {group.items.map((kb) => (
                  <DropdownMenuCheckboxItem
                    key={kb.id}
                    checked={selectedIds.has(kb.id)}
                    onCheckedChange={() => handleToggleKB(kb.id)}
                    onSelect={(e) => e.preventDefault()}
                  >
                    <div className="flex min-w-0 flex-1 items-center gap-2">
                      <span
                        className={cn(
                          "h-2 w-2 shrink-0 rounded-full",
                          kb.status === "active" && "bg-green-500",
                          kb.status === "indexing" && "bg-yellow-500",
                          kb.status !== "active" &&
                            kb.status !== "indexing" &&
                            "bg-red-500",
                        )}
                      />
                      <div className="flex min-w-0 flex-1 flex-col">
                        <span className="truncate text-sm">{kb.name}</span>
                        <span className="text-muted-foreground truncate text-xs">
                          {kb.description ??
                            `${kb.document_count} ${t.knowledgeBase.documentCount}`}
                        </span>
                      </div>
                    </div>
                  </DropdownMenuCheckboxItem>
                ))}
              </div>
            ));
          })()
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

// Exposed for testing (Sprint C.2.2). Production code should not import these.
export const __test_only = {
  knowledgeBaseIdSignature,
  cleanSelection,
};
