"use client";

import { CheckIcon } from "lucide-react";

import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import type { ConversationReference } from "@/core/conversation-references";
import { useI18n } from "@/core/i18n/hooks";
import { useThreads } from "@/core/threads/hooks";
import { titleOfThread } from "@/core/threads/utils";
import { cn } from "@/lib/utils";

type ConversationReferenceListProps = {
  /** The conversation being composed in; it is never offered as a reference. */
  currentThreadId: string;
  selected: ConversationReference[];
  maxReferences: number;
  onToggle: (reference: ConversationReference) => void;
};

/**
 * Recent conversations with a title filter. Selecting a row toggles it; once
 * the per-message cap is reached, unselected rows are disabled while selected
 * rows stay clickable so they can be removed.
 */
export function ConversationReferenceList({
  currentThreadId,
  selected,
  maxReferences,
  onToggle,
}: ConversationReferenceListProps) {
  const { t } = useI18n();
  const { data: threads, isPending } = useThreads();
  const selectedIds = new Set(selected.map((reference) => reference.threadId));
  const atCap = selected.length >= maxReferences;
  const candidates = (threads ?? []).filter(
    (thread) => thread.thread_id !== currentThreadId,
  );

  return (
    <Command className="[&_[cmdk-item]]:px-2 [&_[cmdk-item]]:py-2">
      <CommandInput placeholder={t.inputBox.referenceConversationsSearch} />
      <CommandList>
        {isPending ? (
          // Never claim there are no conversations before the list has loaded.
          <div
            className="text-muted-foreground py-6 text-center text-sm"
            data-testid="conversation-reference-loading"
          >
            {t.common.loading}
          </div>
        ) : (
          <CommandEmpty>{t.inputBox.referenceConversationsEmpty}</CommandEmpty>
        )}
        <CommandGroup>
          {candidates.map((thread) => {
            const title = titleOfThread(thread);
            const isSelected = selectedIds.has(thread.thread_id);
            return (
              <CommandItem
                key={thread.thread_id}
                className={cn("gap-2", isSelected && "text-accent-foreground")}
                data-testid="conversation-reference-option"
                disabled={atCap && !isSelected}
                onSelect={() => onToggle({ threadId: thread.thread_id, title })}
                value={`${title} ${thread.thread_id}`}
              >
                <span className="min-w-0 flex-1 truncate">{title}</span>
                {isSelected ? (
                  <CheckIcon className="size-4 shrink-0" />
                ) : (
                  <span className="size-4 shrink-0" />
                )}
              </CommandItem>
            );
          })}
        </CommandGroup>
      </CommandList>
      <p className="text-muted-foreground border-t px-3 py-2 text-xs">
        {t.inputBox.referenceConversationsLimit(maxReferences)}
      </p>
    </Command>
  );
}

export function ConversationReferencePicker({
  open,
  onOpenChange,
  ...listProps
}: ConversationReferenceListProps & {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useI18n();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="overflow-hidden p-0">
        <DialogTitle className="sr-only">
          {t.inputBox.referenceConversations}
        </DialogTitle>
        <DialogDescription className="sr-only">
          {t.inputBox.referenceConversationsLimit(listProps.maxReferences)}
        </DialogDescription>
        <ConversationReferenceList {...listProps} />
      </DialogContent>
    </Dialog>
  );
}
