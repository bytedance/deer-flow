import { GatewayApiError, UnauthorizedError } from "@/core/api/errors";
import type { Translations } from "@/core/i18n/locales/types";

import { browserTimeZone, formatTaskTime } from "./format";

type ApiErrorKey = keyof Translations["scheduledTasks"]["apiErrors"];

/**
 * Contract code (`detail.code`, contracts/scheduled_task_errors_contract.json
 * `ui_codes`) → `t.scheduledTasks.apiErrors` key. `limits_exhausted` picks
 * between two keys by `params.limit`, so it maps to null here.
 */
export const SCHEDULED_TASK_ERROR_KEYS: Readonly<
  Record<string, ApiErrorKey | null>
> = {
  invalid_request: "invalidRequest",
  invalid_schedule: "invalidSchedule",
  invalid_schedule_type: "invalidScheduleType",
  invalid_timezone: "invalidTimezone",
  interval_too_short: "intervalTooShort",
  interval_too_long: "intervalTooLong",
  once_in_past: "onceInPast",
  once_too_soon: "onceTooSoon",
  once_time_passed: "onceTimePassed",
  invalid_context_mode: "invalidContextMode",
  reuse_thread_requires_thread: "reuseThreadRequiresThread",
  thread_not_found: "threadNotFound",
  invalid_assistant: "invalidAssistant",
  unknown_assistant: "unknownAssistant",
  invalid_goal: "invalidGoal",
  goal_requires_fresh_thread: "goalRequiresFreshThread",
  invalid_stop_condition: "invalidStopCondition",
  invalid_max_runs: "invalidMaxRuns",
  end_at_in_past: "endAtInPast",
  end_at_before_first_run: "endAtBeforeFirstRun",
  frequent_requires_limit: "frequentRequiresLimit",
  max_runs_not_above_used: "maxRunsNotAboveUsed",
  limits_exhausted: null,
  task_not_found: "taskNotFound",
  task_running: "taskRunning",
  run_queued: "runQueued",
  task_changed: "taskChanged",
  task_finished: "taskFinished",
  task_quota_exceeded: "taskQuotaExceeded",
  scheduler_not_running: "schedulerNotRunning",
  scheduler_unavailable: "schedulerUnavailable",
  trigger_failed: "triggerFailed",
};

export type ScheduledTaskErrorDescription = {
  /** Localized text for a toast or an inline message. */
  message: string;
  /** Raw server text for a "Details" disclosure; null when the message says it all. */
  details: string | null;
};

export type DescribeErrorOptions = {
  /** App locale, used to format times inside the message. */
  locale?: string;
  /** Zone for times inside the message (the task's display zone); defaults to the viewer's. */
  timeZone?: string;
  now?: Date;
};

/** False for errors that must not produce a toast (a 401 already redirects to login). */
export function shouldReportScheduledTaskError(error: unknown): boolean {
  return !(error instanceof UnauthorizedError);
}

function interpolate(
  template: string,
  params: Record<string, unknown>,
): string {
  return template.replace(/\{([a-z_]+)\}/g, (match, name: string) => {
    const value = params[name];
    return typeof value === "string" || typeof value === "number"
      ? String(value)
      : match;
  });
}

/**
 * Localized copy for a scheduled-task API error. Known contract codes use
 * their `apiErrors` key with params filled in (times are formatted, never
 * ISO); a 403 with a plain string detail (the shared permission decorator)
 * reads `permissionDenied`; FastAPI's validation list reads `invalidRequest`;
 * anything else reads `generic` with the server text as `details`.
 */
export function describeScheduledTaskError(
  error: unknown,
  t: Pick<Translations, "scheduledTasks">,
  options: DescribeErrorOptions = {},
): ScheduledTaskErrorDescription {
  const labels = t.scheduledTasks.apiErrors;
  if (!(error instanceof GatewayApiError)) {
    const raw = error instanceof Error && error.message ? error.message : null;
    return { message: labels.generic, details: raw };
  }
  if (error.code === null && error.status === 403) {
    return { message: labels.permissionDenied, details: null };
  }
  const code = error.code;
  if (code === "limits_exhausted") {
    const params = { ...error.params };
    if (params.limit === "end_at") {
      const endAt = typeof params.end_at === "string" ? params.end_at : "";
      params.end_at = formatTaskTime(endAt, {
        timeZone: options.timeZone ?? browserTimeZone(),
        locale: options.locale ?? "en-US",
        labels: t.scheduledTasks.time,
        now: options.now,
      });
      return {
        message: interpolate(labels.limitsExhaustedEnd, params),
        details: null,
      };
    }
    return {
      message: interpolate(labels.limitsExhaustedRuns, params),
      details: null,
    };
  }
  const key = code ? SCHEDULED_TASK_ERROR_KEYS[code] : undefined;
  if (key) {
    return {
      message: interpolate(labels[key], error.params),
      details: code === "invalid_request" ? error.rawMessage || null : null,
    };
  }
  return { message: labels.generic, details: error.rawMessage || null };
}
