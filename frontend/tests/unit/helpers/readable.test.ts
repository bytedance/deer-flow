import { describe, expect, it } from "@rstest/core";

import { enUS } from "@/core/i18n/locales/en-US";
import { zhCN } from "@/core/i18n/locales/zh-CN";

import { findRawIdentifiers } from "../../e2e/utils/raw-identifiers";

import { expectNoRawIdentifiers } from "./readable";

function strings(value: unknown, path = ""): Array<[string, string]> {
  if (typeof value === "string") return [[path, value]];
  if (value && typeof value === "object") {
    return Object.entries(value).flatMap(([key, child]) =>
      strings(child, path ? `${path}.${key}` : key),
    );
  }
  return [];
}

describe("raw identifier guard", () => {
  it.each([
    "Run 3f2a9c1e-8b47-4d2a-9e61-5c0b7a1d4e93",
    "task-0123456789abcdef0123",
    "Next run 2026-10-07T01:00:00+00:00",
    "Runs 0 9 * * 1-5",
    "Context: fresh_thread_per_run",
    "Agent: lead_agent",
    "max_runs reached",
    "Status: unmet",
    "Stopped: blocked:needs_user_input",
    "max_continuations_reached",
    "Reason token_capped",
    "thread_changed_after_evaluation",
    "goal_outcome missing",
    "last_evaluation.stand_down_reason",
  ])("flags %s", (text) => {
    expect(findRawIdentifiers(text).length).toBeGreaterThan(0);
  });

  it.each([
    "Weekdays at 09:00 (Asia/Shanghai) · Next: Tomorrow 09:00",
    "工作日 09:00 (Asia/Shanghai) · 下次：明天 09:00",
    "Safety cap: 2 of 5 runs used",
    "Every 30 minutes",
    "Continuation limit reached · 8/8. Reply to keep going.",
    "Token budget reached",
  ])("accepts readable copy: %s", (text) => {
    expectNoRawIdentifiers(text);
  });

  it.each([
    ["en-US", enUS],
    ["zh-CN", zhCN],
  ] as const)(
    "no scheduled-task copy in %s contains a raw identifier",
    (_locale, t) => {
      for (const [path, text] of strings(t.scheduledTasks)) {
        // The cron field's placeholder is the one place a cron belongs.
        if (path === "fields.cronPlaceholder") continue;
        // `{max_runs}`-style placeholders are filled before display.
        const shown = text.replace(/\{[a-z_]+\}/g, "1");
        expect([path, findRawIdentifiers(shown)]).toEqual([path, []]);
      }
    },
  );

  it.each([
    ["en-US", enUS],
    ["zh-CN", zhCN],
  ] as const)(
    "no goal bar copy in %s contains a raw identifier",
    (_locale, t) => {
      for (const [path, text] of strings(t.inputBox.goalBar)) {
        const shown = text.replace(/\{[a-z_]+\}/g, "1");
        expect([path, findRawIdentifiers(shown)]).toEqual([path, []]);
      }
    },
  );
});
