import { describe, expect, it } from "@rstest/core";

import {
  describeGoalBar,
  describeGoalBarCopy,
} from "@/components/workspace/goal-status-helpers";
import { enUS } from "@/core/i18n/locales/en-US";
import type { Translations } from "@/core/i18n/locales/types";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import {
  CHECK_FAILURE_CODES,
  goalReasonKeyOf,
} from "@/core/scheduled-tasks/goal-outcome";

/** The goal bar copy after a goal check that could not run (`code`). */
function uncheckedCopy(code: string, t: Translations) {
  const view = describeGoalBar({
    goal: {
      objective: "ship it",
      status: "active",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:05:00Z",
      continuation_count: 0,
      max_continuations: 8,
      no_progress_count: 0,
      max_no_progress_continuations: 2,
      last_evaluation: {
        satisfied: false,
        blocker: "goal_not_met_yet",
        reason: "The report has no totals yet.",
        stand_down_reason: code,
      },
    },
    outcome: null,
    isRunning: false,
  });
  return describeGoalBarCopy(view, t)!;
}

describe.each([
  ["en-US", enUS],
  ["zh-CN", zhCN],
] as const)("the goal bar after a failed check in %s", (_locale, t) => {
  const label = t.scheduledTasks.goal.unchecked;

  it.each(CHECK_FAILURE_CODES)("says the label once for %s", (code) => {
    const copy = uncheckedCopy(code, t);
    expect(copy.chip).toBe(label);
    expect(copy.detail).not.toContain(label);
    expect(copy.announcement.split(label)).toHaveLength(2);
  });

  it.each(CHECK_FAILURE_CODES)("keeps why the check failed for %s", (code) => {
    // The scheduled page's reason is the label, then why; the bar keeps why.
    const scheduled = t.scheduledTasks.goal.reasons[goalReasonKeyOf(code)!];
    expect(scheduled.startsWith(label)).toBe(true);
    const why = scheduled.slice(label.length).replace(/^[;:，：]\s*/, "");
    expect(why).not.toBe("");
    expect(uncheckedCopy(code, t).detail?.toLowerCase()).toContain(
      why.toLowerCase(),
    );
  });
});
