"use client";

import { toast } from "sonner";

import type { Translations } from "@/core/i18n/locales/types";

import type { ScheduledTaskErrorDescription } from "./errors";

type ErrorLabels = Pick<Translations, "scheduledTasks">;

/**
 * The raw server text behind a collapsed "Details" disclosure (spec T6):
 * kept out of the default view, never thrown away. Renders nothing when the
 * localized message says it all.
 */
export function ErrorDetails({
  details,
  label,
}: {
  details: string | null;
  label: string;
}) {
  if (!details) {
    return null;
  }
  return (
    <details className="text-xs" data-testid="scheduled-task-error-details">
      <summary className="w-fit cursor-pointer select-none">{label}</summary>
      <pre className="mt-1 max-h-40 overflow-auto font-mono break-words whitespace-pre-wrap">
        {details}
      </pre>
    </details>
  );
}

/** "Failed to pause scheduled task: …" / "暂停定时任务失败：…" with the locale's colon. */
export function errorWithReason(
  t: ErrorLabels,
  action: string,
  reason: string,
): string {
  return t.scheduledTasks.errors.withReason
    .replace("{action}", action)
    .replace("{reason}", reason);
}

/** Toast a failed action; any raw server text sits behind "Details". */
export function toastScheduledTaskError(
  t: ErrorLabels,
  action: string,
  { message, details }: ScheduledTaskErrorDescription,
): void {
  toast.error(errorWithReason(t, action, message), {
    description: details ? (
      <ErrorDetails
        details={details}
        label={t.scheduledTasks.history.details}
      />
    ) : undefined,
  });
}
