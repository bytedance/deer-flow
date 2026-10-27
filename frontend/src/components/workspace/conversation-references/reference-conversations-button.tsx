"use client";

import { MessagesSquareIcon } from "lucide-react";
import { useCallback, useState } from "react";

import { PromptInputButton } from "@/components/ai-elements/prompt-input";
import type { ConversationReference } from "@/core/conversation-references";
import { useConversationReferencesCapability } from "@/core/features/hooks";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { Tooltip } from "../tooltip";

import { ConversationReferencePicker } from "./conversation-reference-picker";

/**
 * Composer entry point for attaching conversations to the next message.
 * Renders nothing unless `/api/features` reports `read_conversation` enabled,
 * so deployments without the tool see no change.
 */
export function ReferenceConversationsButton({
  className,
  currentThreadId,
  disabled,
  references,
  onChange,
}: {
  className?: string;
  currentThreadId: string;
  disabled?: boolean;
  references: ConversationReference[];
  onChange: (references: ConversationReference[]) => void;
}) {
  const { t } = useI18n();
  const { enabled, maxReferences } = useConversationReferencesCapability();
  const [open, setOpen] = useState(false);

  const toggle = useCallback(
    (reference: ConversationReference) => {
      if (references.some((item) => item.threadId === reference.threadId)) {
        onChange(
          references.filter((item) => item.threadId !== reference.threadId),
        );
        return;
      }
      if (references.length >= maxReferences) {
        return;
      }
      onChange([...references, reference]);
    },
    [references, maxReferences, onChange],
  );

  if (!enabled || maxReferences <= 0) {
    return null;
  }

  return (
    <>
      <Tooltip content={t.inputBox.referenceConversations}>
        <PromptInputButton
          aria-label={t.inputBox.referenceConversations}
          className={cn("gap-1 px-2!", className)}
          data-testid="reference-conversations-button"
          disabled={disabled}
          onClick={() => setOpen(true)}
        >
          <MessagesSquareIcon className="size-3" />
          {references.length > 0 && (
            <span className="text-xs">{references.length}</span>
          )}
        </PromptInputButton>
      </Tooltip>
      <ConversationReferencePicker
        currentThreadId={currentThreadId}
        maxReferences={maxReferences}
        onOpenChange={setOpen}
        onToggle={toggle}
        open={open}
        selected={references}
      />
    </>
  );
}
