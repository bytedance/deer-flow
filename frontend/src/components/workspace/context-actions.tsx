"use client";

import { Eraser, Loader2Icon, Minimize2 } from "lucide-react";
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
import { useI18n } from "@/core/i18n/hooks";
import {
  useClearContext,
  useCompactContext,
} from "@/core/threads/hooks";

import { useThread } from "./messages/context";
import { Tooltip } from "./tooltip";

export function ContextActions({ threadId }: { threadId: string }) {
  const { t } = useI18n();
  const { thread } = useThread();
  const [clearDialogOpen, setClearDialogOpen] = useState(false);

  const messages = thread.messages;
  const hasMessages = messages.length > 0;

  const clearMutation = useClearContext();
  const compactMutation = useCompactContext();

  if (!hasMessages) {
    return null;
  }

  return (
    <>
      <Tooltip content={t.conversation.clearContext}>
        <Button
          className="text-muted-foreground hover:text-foreground"
          variant="ghost"
          size="icon"
          onClick={() => setClearDialogOpen(true)}
          disabled={clearMutation.isPending || compactMutation.isPending}
        >
          {clearMutation.isPending ? (
            <Loader2Icon className="size-4 animate-spin" />
          ) : (
            <Eraser className="size-4" />
          )}
        </Button>
      </Tooltip>
      <Tooltip content={t.conversation.compact}>
        <Button
          className="text-muted-foreground hover:text-foreground"
          variant="ghost"
          size="icon"
          onClick={() => compactMutation.mutate({ threadId })}
          disabled={clearMutation.isPending || compactMutation.isPending}
        >
          {compactMutation.isPending ? (
            <Loader2Icon className="size-4 animate-spin" />
          ) : (
            <Minimize2 className="size-4" />
          )}
        </Button>
      </Tooltip>

      <Dialog open={clearDialogOpen} onOpenChange={setClearDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {t.conversation.clearContextConfirmTitle}
            </DialogTitle>
            <DialogDescription>
              {t.conversation.clearContextConfirmDescription}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setClearDialogOpen(false)}
            >
              {t.common.cancel}
            </Button>
            <Button
              variant="destructive"
              disabled={clearMutation.isPending}
              onClick={() => {
                clearMutation.mutate(
                  { threadId },
                  {
                    onSuccess: () => {
                      setClearDialogOpen(false);
                    },
                  },
                );
              }}
            >
              {clearMutation.isPending
                ? t.common.loading
                : t.conversation.clearContext}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
