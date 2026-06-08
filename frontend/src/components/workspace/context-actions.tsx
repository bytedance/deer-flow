"use client";

import { Eraser, Loader2, Minimize2, X } from "lucide-react";
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
} from "react";
import { toast } from "sonner";

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
import { useClearContext, useCompactContext } from "@/core/threads/hooks";
import { cn } from "@/lib/utils";

import { useThread } from "./messages/context";
import { Tooltip } from "./tooltip";

/**
 * Lightweight in-session event so the chat view can render a divider
 * after a manual /clear or /compact. State lives in a React context
 * (not the backend) so the marker disappears on page refresh — its only
 * purpose is to give the user immediate visual feedback within the
 * current session. ``timestamp`` exists to key animations / dedupe.
 */
export interface ContextEvent {
  type: "clear" | "compact";
  summary?: string;
  timestamp: number;
}

interface ContextEventCtx {
  event: ContextEvent | null;
  setEvent: (event: ContextEvent | null) => void;
}

const ContextEventContext = createContext<ContextEventCtx>({
  event: null,
  setEvent: () => undefined,
});

export function useContextEvent() {
  return useContext(ContextEventContext);
}

export function ContextEventProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [event, setEvent] = useState<ContextEvent | null>(null);
  const value = useMemo(() => ({ event, setEvent }), [event]);
  return (
    <ContextEventContext.Provider value={value}>
      {children}
    </ContextEventContext.Provider>
  );
}

export function ContextActions({ threadId }: { threadId: string }) {
  const { t } = useI18n();
  const { thread } = useThread();
  const { setEvent } = useContextEvent();
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
        onSuccess: () => {
          setEvent({ type: "clear", timestamp: Date.now() });
          toast.success(t.conversation.clearContextSuccess);
        },
        onError: (err) =>
          toast.error(err.message || t.conversation.clearContextError),
      },
    );
  };

  const handleCompact = () => {
    compactMutation.mutate(
      { threadId },
      {
        onSuccess: (data) => {
          setEvent({
            type: "compact",
            summary: data.summary,
            timestamp: Date.now(),
          });
          toast.success(t.conversation.compactContextSuccess);
        },
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

/**
 * Inline divider rendered between the message list and the input box
 * after a successful manual /clear or /compact. Shows the summary in a
 * collapsible panel for compact events. State is held in
 * ``ContextEventContext`` so it disappears on refresh — same scope as
 * a toast, but persistent within the session.
 */
export function ContextEventDivider({
  className,
}: {
  className?: string;
}) {
  const { t } = useI18n();
  const { event, setEvent } = useContextEvent();
  const dismiss = useCallback(() => setEvent(null), [setEvent]);

  if (!event) return null;

  const label =
    event.type === "clear"
      ? t.conversation.clearContextSuccess
      : t.conversation.compactContextSuccess;

  return (
    <div className={cn("flex flex-col items-stretch gap-1 py-2", className)}>
      <div className="bg-muted/60 text-muted-foreground flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-xs">
        <div className="bg-border h-px flex-1" />
        <span className="shrink-0">{label}</span>
        <div className="bg-border h-px flex-1" />
        <button
          type="button"
          className="hover:text-foreground -mr-1 shrink-0 cursor-pointer rounded p-0.5"
          onClick={dismiss}
          aria-label={t.conversation.cancel}
        >
          <X className="size-3" />
        </button>
      </div>
      {event.type === "compact" && event.summary && (
        <Collapsible className="w-full">
          <CollapsibleTrigger className="text-muted-foreground hover:text-foreground w-full cursor-pointer text-center text-xs">
            {t.conversation.compactSummary}
          </CollapsibleTrigger>
          <CollapsibleContent>
            <div className="bg-muted/40 mt-1 max-h-96 overflow-y-auto rounded-md p-3 text-xs whitespace-pre-wrap">
              {event.summary}
            </div>
          </CollapsibleContent>
        </Collapsible>
      )}
    </div>
  );
}
