"use client";

import { useId, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useI18n } from "@/core/i18n/hooks";
import {
  utcToZonedLocalInput,
  validZonedLocalToUtcIso,
} from "@/core/scheduled-tasks/cron";
import { ErrorDetails } from "@/core/scheduled-tasks/error-toast";
import {
  describeScheduledTaskError,
  type ScheduledTaskErrorDescription,
} from "@/core/scheduled-tasks/errors";
import { displayTimeZone, formatTaskTime } from "@/core/scheduled-tasks/format";
import { useResumeScheduledTask } from "@/core/scheduled-tasks/hooks";
import type {
  ScheduledTask,
  ScheduledTaskRenewal,
} from "@/core/scheduled-tasks/types";

import { fill, isFrequentSchedule } from "./shared";

type RenewTask = Pick<
  ScheduledTask,
  | "id"
  | "max_runs"
  | "end_at"
  | "automatic_runs_used"
  | "origin_thread_id"
  | "schedule_type"
  | "schedule_spec"
  | "timezone"
>;

/**
 * Build the resume body from the dialog state: a removed cap is sent as
 * `null`, a changed value as the new value, an untouched cap not at all.
 */
export function renewalFromForm(
  task: Pick<ScheduledTask, "max_runs" | "end_at">,
  form: {
    maxRuns: string;
    removeMaxRuns: boolean;
    endAt: string | null;
    removeEndAt: boolean;
  },
): ScheduledTaskRenewal | "invalid" {
  const renewal: ScheduledTaskRenewal = {};
  if (form.removeMaxRuns) {
    renewal.max_runs = null;
  } else if (form.maxRuns.trim() !== "") {
    const value = Number(form.maxRuns);
    if (!Number.isInteger(value) || value < 1) {
      return "invalid";
    }
    if (value !== task.max_runs) {
      renewal.max_runs = value;
    }
  }
  if (form.removeEndAt) {
    renewal.end_at = null;
  } else if (form.endAt) {
    const changed =
      !task.end_at || Date.parse(form.endAt) !== Date.parse(task.end_at);
    if (changed) {
      renewal.end_at = form.endAt;
    }
  }
  return renewal;
}

/**
 * "Extend the safety cap": raise or remove the run limit and/or move or
 * remove the end time, then resume, in one request. Removing the last cap of
 * a chat-created task that runs more often than hourly is not offered (the
 * server enforces the same rule).
 */
export function RenewLimitsDialog({
  task,
  open,
  onOpenChange,
  onResumed,
}: {
  task: RenewTask;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onResumed?: (task: ScheduledTask) => void;
}) {
  const { t, locale } = useI18n();
  const st = t.scheduledTasks;
  const timeZone = displayTimeZone(task);
  const used = task.automatic_runs_used ?? 0;
  const ids = useId();
  const [maxRuns, setMaxRuns] = useState(
    task.max_runs != null ? String(task.max_runs) : "",
  );
  const [removeMaxRuns, setRemoveMaxRuns] = useState(false);
  const [endAtLocal, setEndAtLocal] = useState(
    task.end_at ? utcToZonedLocalInput(task.end_at, timeZone) : "",
  );
  const [removeEndAt, setRemoveEndAt] = useState(false);
  const [error, setError] = useState<ScheduledTaskErrorDescription | null>(
    null,
  );
  const resume = useResumeScheduledTask({ toastOnError: false });

  const hasRunsCap = task.max_runs != null;
  const hasEndCap = task.end_at != null;
  const runsExhausted = hasRunsCap && used >= (task.max_runs ?? 0);
  const endPassed = hasEndCap && Date.parse(task.end_at ?? "") <= Date.now();
  const needsCap =
    task.origin_thread_id != null &&
    isFrequentSchedule(task.schedule_type, task.schedule_spec);
  // Removing a cap is blocked when the other one is absent or removed too.
  const removeRunsBlocked = needsCap && (!hasEndCap || removeEndAt);
  const removeEndBlocked = needsCap && (!hasRunsCap || removeMaxRuns);

  const endAtIso = endAtLocal
    ? validZonedLocalToUtcIso(endAtLocal, timeZone)
    : null;
  const renewal = renewalFromForm(task, {
    maxRuns,
    removeMaxRuns,
    endAt: endAtIso,
    removeEndAt,
  });
  const canSubmit =
    renewal !== "invalid" &&
    Object.keys(renewal).length > 0 &&
    !(endAtLocal && !endAtIso) &&
    !resume.isPending;

  const body = runsExhausted
    ? fill(st.renew.bodyRuns, { used, max: task.max_runs ?? 0 })
    : endPassed
      ? fill(st.renew.bodyEnd, {
          time: formatTaskTime(task.end_at ?? "", {
            timeZone,
            locale,
            labels: st.time,
          }),
        })
      : hasEndCap && !hasRunsCap
        ? st.notice.limitBodyEnd
        : st.notice.limitBodyRuns;

  const submit = () => {
    if (renewal === "invalid" || !canSubmit) {
      return;
    }
    setError(null);
    resume.mutate(
      { taskId: task.id, renewal },
      {
        onSuccess: (resumed) => {
          onOpenChange(false);
          onResumed?.(resumed);
        },
        onError: (cause) =>
          setError(describeScheduledTaskError(cause, t, { locale, timeZone })),
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{st.renew.title}</DialogTitle>
          <DialogDescription>{body}</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-4">
          {(hasRunsCap || !hasEndCap) && (
            <div className="flex flex-col gap-1.5">
              <label
                htmlFor={`${ids}-max-runs`}
                className="text-sm font-medium"
              >
                {st.form.maxRuns}
              </label>
              <Input
                id={`${ids}-max-runs`}
                type="number"
                inputMode="numeric"
                min={used + 1}
                value={maxRuns}
                disabled={removeMaxRuns}
                onChange={(event) => setMaxRuns(event.target.value)}
              />
              <p className="text-muted-foreground text-xs">
                {fill(st.form.maxRunsHint, { used })}
              </p>
              {hasRunsCap && (
                <RemoveCapToggle
                  id={`${ids}-remove-max-runs`}
                  checked={removeMaxRuns}
                  blocked={removeRunsBlocked}
                  onChange={setRemoveMaxRuns}
                />
              )}
            </div>
          )}
          {(hasEndCap || !hasRunsCap) && (
            <div className="flex flex-col gap-1.5">
              <label htmlFor={`${ids}-end-at`} className="text-sm font-medium">
                {fill(st.form.labelWithZone, {
                  label: st.form.endAt,
                  tz: timeZone,
                })}
              </label>
              <Input
                id={`${ids}-end-at`}
                type="datetime-local"
                value={endAtLocal}
                disabled={removeEndAt}
                aria-invalid={Boolean(endAtLocal && !endAtIso)}
                onChange={(event) => setEndAtLocal(event.target.value)}
              />
              {hasEndCap && (
                <RemoveCapToggle
                  id={`${ids}-remove-end-at`}
                  checked={removeEndAt}
                  blocked={removeEndBlocked}
                  onChange={setRemoveEndAt}
                />
              )}
            </div>
          )}
          {renewal === "invalid" && (
            <p role="alert" className="text-destructive text-sm">
              {st.apiErrors.invalidMaxRuns}
            </p>
          )}
          {error && (
            <div className="text-destructive flex flex-col gap-1">
              <p role="alert" className="text-sm">
                {error.message}
              </p>
              <ErrorDetails
                details={error.details}
                label={st.history.details}
              />
            </div>
          )}
        </div>
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={resume.isPending}
          >
            {t.common.cancel}
          </Button>
          <Button onClick={submit} disabled={!canSubmit}>
            {st.renew.submit}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function RemoveCapToggle({
  id,
  checked,
  blocked,
  onChange,
}: {
  id: string;
  checked: boolean;
  blocked: boolean;
  onChange: (checked: boolean) => void;
}) {
  const { t } = useI18n();
  const st = t.scheduledTasks;
  return (
    <div className="flex flex-col gap-0.5">
      <label
        htmlFor={id}
        className="flex w-fit items-center gap-2 text-sm aria-disabled:opacity-60"
        aria-disabled={blocked && !checked ? true : undefined}
      >
        <input
          id={id}
          type="checkbox"
          className="size-4"
          checked={checked}
          disabled={blocked && !checked}
          aria-describedby={blocked && !checked ? `${id}-blocked` : undefined}
          onChange={(event) => onChange(event.target.checked)}
        />
        {st.renew.removeCap}
      </label>
      {blocked && !checked && (
        <p id={`${id}-blocked`} className="text-muted-foreground text-xs">
          {st.renew.removeCapBlocked}
        </p>
      )}
    </div>
  );
}
