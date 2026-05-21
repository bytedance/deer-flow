"use client";

import { Eraser, Loader2, Minimize2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

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
import { useClearContext, useCompactContext } from "@/core/threads/hooks";

import { useThread } from "./messages/context";
import { Tooltip } from "./tooltip";

export function ContextActions({ threadId }: { threadId: string }) {
  const { t } = useI18n();
  const { thread } = useThread();
  const clearMutation = useClearContext();
  const compactMutation = useCompactContext();
  const [confirmOpen, setConfirmOpen] = useState(false);

  const hasMessages = thread.messages.length > 0;
  if (!hasMessages) {
    return null;
  }

  const isBusy =
    thread.isLoading ||
    clearMutation.isPending ||
    compactMutation.isPending;

  const handleClear = () => {
    setConfirmOpen(false);
    clearMutation.mutate(
      { threadId },
      {
        onSuccess: () => toast.success(t.conversation.clearContextSuccess),
        onError: (err) =>
          toast.error(err.message || t.conversation.clearContextError),
      },
    );
  };

  const handleCompact = () => {
    compactMutation.mutate(
      { threadId },
      {
        onSuccess: () => toast.success(t.conversation.compactContextSuccess),
        onError: (err) =>
          toast.error(err.message || t.conversation.compactContextError),
      },
    );
  };

  return (
    <>
      <Tooltip content={t.conversation.clearContextTooltip}>
        <Button
          className="text-muted-foreground hover:text-foreground"
          variant="ghost"
          size="icon"
          disabled={isBusy}
          onClick={() => setConfirmOpen(true)}
          aria-label={t.conversation.clearContext}
        >
          {clearMutation.isPending ? (
            <Loader2 className="animate-spin" />
          ) : (
            <Eraser />
          )}
        </Button>
      </Tooltip>
      <Tooltip content={t.conversation.compactContextTooltip}>
        <Button
          className="text-muted-foreground hover:text-foreground"
          variant="ghost"
          size="icon"
          disabled={isBusy}
          onClick={handleCompact}
          aria-label={t.conversation.compactContext}
        >
          {compactMutation.isPending ? (
            <Loader2 className="animate-spin" />
          ) : (
            <Minimize2 />
          )}
        </Button>
      </Tooltip>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {t.conversation.clearContextConfirmTitle}
            </DialogTitle>
            <DialogDescription>
              {t.conversation.clearContextConfirmDesc}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)}>
              {t.conversation.cancel}
            </Button>
            <Button variant="destructive" onClick={handleClear}>
              {t.conversation.clearContextConfirm}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
