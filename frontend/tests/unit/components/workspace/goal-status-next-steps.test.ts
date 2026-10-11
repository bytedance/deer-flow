import { describe, expect, it } from "@rstest/core";

import {
  describeGoalBar,
  describeGoalBarCopy,
} from "@/components/workspace/goal-status-helpers";
import { enUS } from "@/core/i18n/locales/en-US";
import type { Translations } from "@/core/i18n/locales/types";
import { zhCN } from "@/core/i18n/locales/zh-CN";

const LOCALES = [
  {
    locale: "en-US",
    t: enUS,
    askForResult: "Ask it to show the result",
    replyWithRest: "what's left",
    noLongerApplies: "if the goal no longer applies",
  },
  {
    locale: "zh-CN",
    t: zhCN,
    askForResult: "让它展示结果",
    replyWithRest: "还差什么",
    noLongerApplies: "如果目标已不适用",
  },
] as const;

/** The goal bar's second line for a goal the host stood down with `code`. */
function detailOf(code: string, t: Translations) {
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
    hasOpenHumanInputCard: false,
  });
  return describeGoalBarCopy(view, t)?.detail ?? "";
}

describe.each(LOCALES)(
  "goal bar next steps in $locale",
  ({ t, askForResult, replyWithRest, noLongerApplies }) => {
    it("asks the agent for missing evidence, not the user for the rest", () => {
      const detail = detailOf("blocked:missing_evidence", t);
      expect(detail).toContain(askForResult);
      expect(detail).not.toContain(replyWithRest);
      expect(detail).toContain("/goal clear");
    });

    it("offers /goal clear only for a goal that no longer applies", () => {
      // Clearing drops the met record, so work that is right would never
      // show "Goal met".
      for (const text of Object.values(t.inputBox.goalBar.next)) {
        if (text.includes("/goal clear")) {
          expect(text).toContain(noLongerApplies);
        }
      }
    });
  },
);
