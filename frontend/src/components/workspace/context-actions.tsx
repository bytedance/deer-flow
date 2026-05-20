"use client";

import { Eraser, Loader2Icon, Minimize2 } from "lucide-react";
import { createContext, useContext, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useI18n } from "@/core/i18n/hooks";
import type { ContextUsage } from "@/core/threads/api";
import {
  useClearContext,
  useCompactContext,
} from "@/core/threads/hooks";

import { useThread } from "./messages/context";
import { Tooltip } from "./tooltip";

export interface ContextEvent {
  type: "clear" | "compact";
  summary?: string;
  timestamp: number;
  contextUsage?: ContextUsage | null;
}

export const ContextEventContext = createContext<{
  event: ContextEvent | null;
  setEvent: (event: ContextEvent | null) => void;
}>({
  event: null,
  setEvent: (_event: ContextEvent | null) => void _event,
});

export function useContextEvent() {
  return useContext(ContextEventContext);
}

function formatPercentage(percentage: number | null | undefined): string {
  if (percentage == null) return "";
  return `${percentage}%`;
}

export function ContextActions({ threadId }: { threadId: string }) {
  const { t } = useI18n();
  const { thread } = useThread();
  const [clearDialogOpen, setClearDialogOpen] = useState(false);
  const { setEvent } = useContextEvent();

  const messages = thread.messages;
  const hasMessages = messages.length > 0;

  const clearMutation = useClearContext();
  const compactMutation = useCompactContext();

  if (!hasMessages) {
    return null;
  }

  return (
    <>
      <Tooltip
        content={
          compactMutation.data?.context_usage?.percentage != null
            ? `${t.conversation.clearContext} (${formatPercentage(compactMutation.data.context_usage.percentage)} used)`
            : t.conversation.clearContext
        }
      >
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
          onClick={() =>
            compactMutation.mutate(
              { threadId },
              {
                onSuccess: (data) => {
                  setEvent({
                    type: "compact",
                    summary: data.summary ?? undefined,
                    timestamp: Date.now(),
                    contextUsage: data.context_usage,
                  });
                },
              },
            )
          }
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
                    onSuccess: (data) => {
                      setClearDialogOpen(false);
                      setEvent({
                        type: "clear",
                        timestamp: Date.now(),
                        contextUsage: data.context_usage,
                      });
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

export function ContextEventDivider() {
  const { t } = useI18n();
  const { event, setEvent } = useContextEvent();

  if (!event) return null;

  const usage = event.contextUsage;
  const percentageStr = usage?.percentage != null
    ? ` · ${usage.percentage}% context`
    : "";

  return (
    <div className="flex flex-col items-center gap-2 py-4">
      <div className="bg-muted flex w-full items-center gap-2 rounded-lg px-4 py-2 text-xs">
        <div className="bg-border h-px flex-1" />
        <span className="text-muted-foreground shrink-0">
          {event.type === "clear"
            ? `✂ ${t.conversation.clearContextSuccess}${percentageStr}`
            : `📦 ${t.conversation.compactSuccess}${percentageStr}`}
        </span>
        <div className="bg-border h-px flex-1" />
        <button
          className="text-muted-foreground hover:text-foreground ml-1 shrink-0 cursor-pointer"
          onClick={() => setEvent(null)}
        >
          ✕
        </button>
      </div>
      {event.type === "compact" && event.summary && (
        <Collapsible className="w-full">
          <CollapsibleTrigger className="text-muted-foreground hover:text-foreground w-full text-center text-xs cursor-pointer">
            {t.conversation.compactSummary} ▾
          </CollapsibleTrigger>
          <CollapsibleContent>
            <div className="bg-muted/50 mt-1 rounded-lg p-3 text-sm whitespace-pre-wrap">
              {event.summary}
            </div>
          </CollapsibleContent>
        </Collapsible>
      )}
    </div>
  );
}
