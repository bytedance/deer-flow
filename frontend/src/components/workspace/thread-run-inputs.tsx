"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Clock3, RotateCcw, X } from "lucide-react";
import { useContext, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { AuthQueryScopeContext } from "@/core/auth/query-scope";
import { useI18n } from "@/core/i18n/hooks";
import {
  changeRunInput,
  runInputsKey,
  type RunInput,
} from "@/core/threads/run-inputs";

export function ThreadRunInputs({
  threadId,
  isRunning,
  canCreate,
  canCancel,
  inputs,
}: {
  threadId?: string;
  isRunning: boolean;
  canCreate: boolean;
  canCancel: boolean;
  inputs: RunInput[];
}) {
  const account = useContext(AuthQueryScopeContext);
  const { t } = useI18n();
  const client = useQueryClient();
  const [busy, setBusy] = useState<string | null>(null);
  const action = useRef<AbortController | null>(null);
  useEffect(() => {
    setBusy(null);
    return () => action.current?.abort();
  }, [account, threadId]);
  const items = inputs.filter(
    (x) => x.status !== "applied" && x.status !== "cancelled",
  );
  async function change(input: RunInput, operation: "cancel" | "retry") {
    if (!threadId || busy) return;
    const controller = new AbortController();
    action.current = controller;
    setBusy(input.id);
    try {
      await changeRunInput(threadId, input, operation, controller.signal);
      if (!controller.signal.aborted) {
        await client.invalidateQueries({ queryKey: runInputsKey(threadId) });
        await client.invalidateQueries({ queryKey: ["thread", threadId] });
      }
    } catch {
      if (!controller.signal.aborted)
        toast.error(t.inputBox.runInputUnavailable);
    } finally {
      if (!controller.signal.aborted) setBusy(null);
    }
  }
  if (!items.length) return null;
  return (
    <div
      className="mb-2 max-h-36 space-y-1 overflow-y-auto rounded-lg border px-3 py-2"
      data-testid="run-inputs"
      aria-live="polite"
    >
      {items.map((input) => (
        <div
          key={`${input.target_run_id}:${input.id}`}
          className="flex min-w-0 items-center gap-2 text-sm"
          data-testid="run-input-item"
          data-input-status={input.status}
        >
          <Clock3
            className="text-muted-foreground size-3.5 shrink-0"
            aria-hidden
          />
          <span className="text-muted-foreground shrink-0 text-xs">
            {input.status === "not_applied"
              ? t.inputBox.runInputUnapplied
              : input.status === "dispatching"
                ? t.inputBox.runInputDispatching
                : input.mode === "queue"
                  ? t.inputBox.runInputQueued
                  : t.inputBox.runInputSteering}
          </span>
          <span className="min-w-0 flex-1 truncate" title={input.text}>
            {input.text}
          </span>
          {!isRunning && canCreate && (
            <Button
              size="icon-sm"
              variant="ghost"
              aria-label={t.inputBox.runInputRetry}
              title={t.inputBox.runInputRetry}
              disabled={busy !== null}
              onClick={() => void change(input, "retry")}
            >
              <RotateCcw className="size-3.5" />
            </Button>
          )}
          {canCancel &&
            input.status !== "dispatching" &&
            input.status !== "applying" && (
              <Button
                size="icon-sm"
                variant="ghost"
                aria-label={t.inputBox.runInputCancel}
                title={t.inputBox.runInputCancel}
                disabled={busy !== null}
                onClick={() => void change(input, "cancel")}
              >
                <X className="size-3.5" />
              </Button>
            )}
        </div>
      ))}
    </div>
  );
}
