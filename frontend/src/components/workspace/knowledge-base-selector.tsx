"use client";

import { BookOpenIcon, Loader2Icon } from "lucide-react";
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

  const hasCleaned = useRef(false);
  useEffect(() => {
    if (isLoading || hasCleaned.current || !selection?.enabled) return;
    if (knowledgeBases.length === 0) return;

    const validIds = new Set(knowledgeBases.map((kb) => kb.id));
    const filtered = selection.selected_ids.filter((id) => validIds.has(id));
    if (filtered.length < selection.selected_ids.length) {
      hasCleaned.current = true;
      onSelectionChange({
        enabled: filtered.length > 0,
        selected_ids: filtered,
      });
    }
  }, [isLoading, knowledgeBases, selection, onSelectionChange]);

  const handleToggleKB = useCallback(
    (id: string) => {
      const next = new Set(selectedIds);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      const ids = Array.from(next);
      onSelectionChange({
        enabled: ids.length > 0,
        selected_ids: ids,
      });
    },
    [selectedIds, onSelectionChange],
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
          knowledgeBases.map((kb) => (
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
          ))
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
