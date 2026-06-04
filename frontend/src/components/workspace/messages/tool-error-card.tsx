"use client";

import { AlertCircleIcon, ChevronDownIcon, ChevronRightIcon, RefreshCwIcon } from "@/components/ui/icons";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { type ErrorCategory, type ToolErrorInfo, isRetryableError } from "@/core/messages/tool-errors";

function useErrorText(category: ErrorCategory): string {
  const { t } = useI18n();
  const map: Record<ErrorCategory, string> = {
    network_issue: t.errors.network_issue,
    timeout: t.errors.timeout,
    service_unavailable: t.errors.service_unavailable,
    data_not_found: t.errors.data_not_found,
    permission_denied: t.errors.permission_denied,
    rate_limited: t.errors.rate_limited,
  };
  return map[category] ?? t.errors.service_unavailable;
}

export function ToolErrorCard({ errorInfo }: { errorInfo: ToolErrorInfo }) {
  const { t } = useI18n();
  const [showDetails, setShowDetails] = useState(false);
  const errorText = useErrorText(errorInfo.category);
  const canRetry = isRetryableError(errorInfo.category);

  return (
    <div className="border-destructive/30 bg-destructive/5 my-2 rounded-lg border p-3">
      <div className="flex items-start gap-2">
        <AlertCircleIcon className="text-destructive mt-0.5 size-4 shrink-0" />
        <div className="min-w-0 flex-1">
          <p className="text-sm leading-relaxed">{errorText}</p>
          <div className="mt-2 flex items-center gap-2">
            <button
              type="button"
              className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs transition-colors"
              onClick={() => setShowDetails(!showDetails)}
            >
              {showDetails ? (
                <ChevronDownIcon className="size-3" />
              ) : (
                <ChevronRightIcon className="size-3" />
              )}
              {showDetails ? t.errors.hideDetails : t.errors.showDetails}
            </button>
            {canRetry && (
              <Button
                variant="ghost"
                size="sm"
                className="h-6 gap-1 px-2 text-xs"
                onClick={() => {
                  // Retry is handled by re-submitting the last user message.
                  // The parent component wires this to the thread's retry callback.
                  window.dispatchEvent(
                    new CustomEvent("deerflow:retry-last-turn"),
                  );
                }}
              >
                <RefreshCwIcon className="size-3" />
                {t.errors.retry}
              </Button>
            )}
          </div>
        </div>
      </div>
      {showDetails && (
        <div className={cn("border-border/50 mt-2 border-t pt-2")}>
          <p className="text-muted-foreground font-mono text-xs whitespace-pre-wrap">
            {errorInfo.rawMessage}
          </p>
        </div>
      )}
    </div>
  );
}
