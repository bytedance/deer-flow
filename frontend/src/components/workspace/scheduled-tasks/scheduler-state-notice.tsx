"use client";

import { CalendarOff, CirclePause } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { useI18n } from "@/core/i18n/hooks";

/**
 * Explains a server without the scheduler (`available: false`, the page has
 * nothing to show) or with automatic runs off (`running: false`, tasks stay
 * visible and can still run once now, but none can be created).
 */
export function SchedulerStateNotice({
  available,
  running,
}: {
  available: boolean;
  running: boolean;
}) {
  const { t } = useI18n();
  const st = t.scheduledTasks;
  if (!available) {
    return (
      <div
        className="flex flex-col items-center gap-2 rounded-lg border border-dashed px-6 py-12 text-center"
        data-testid="scheduled-tasks-unavailable"
      >
        <CalendarOff className="text-muted-foreground size-6" aria-hidden />
        <h2 className="text-base font-semibold">{st.page.unavailableTitle}</h2>
        <p className="text-muted-foreground text-sm">
          {st.page.unavailableBody}
        </p>
      </div>
    );
  }
  if (running) {
    return null;
  }
  return (
    <Alert
      className="border-amber-500/50 bg-amber-500/10"
      data-testid="scheduler-off-notice"
    >
      <CirclePause className="text-amber-600 dark:text-amber-400" />
      <AlertTitle>{st.page.schedulerOffTitle}</AlertTitle>
      <AlertDescription>{st.page.schedulerOffBody}</AlertDescription>
    </Alert>
  );
}
