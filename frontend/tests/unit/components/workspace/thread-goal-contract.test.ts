import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "@rstest/core";

import {
  describeGoalBar,
  describeGoalBarCopy,
  GOAL_HOST_REASON_TEXTS,
  GOAL_OUTCOME_KEYS,
  isThreadGoalOutcome,
} from "@/components/workspace/goal-status-helpers";
import { enUS } from "@/core/i18n/locales/en-US";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import { CHECK_FAILURE_CODES } from "@/core/scheduled-tasks/goal-outcome";
import type { GoalState } from "@/core/threads/types";

import { findRawIdentifiers } from "../../../e2e/utils/raw-identifiers";

type ContractFile = {
  version: number;
  stand_down_reason_codes: string[];
  check_failure_codes: string[];
  goal_outcome: { channel: string; statuses: string[]; keys: string[] };
  history_head_keys: string[];
  host_reason_texts: string[];
};

const CONTRACT = JSON.parse(
  readFileSync(
    resolve(__dirname, "../../../../../contracts/thread_goal_contract.json"),
    "utf-8",
  ),
) as ContractFile;

function stoodDown(code: string): GoalState {
  return {
    objective: "ship it",
    status: "active",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:05:00Z",
    continuation_count: 8,
    max_continuations: 8,
    no_progress_count: 0,
    max_no_progress_continuations: 2,
    last_evaluation: {
      satisfied: false,
      blocker: "goal_not_met_yet",
      reason: "Totals missing.",
      stand_down_reason: code,
    },
  };
}

describe("thread goal contract", () => {
  it.each(CONTRACT.stand_down_reason_codes)(
    "%s has its own readable stop copy in en-US and zh-CN",
    (code) => {
      for (const hasOpenHumanInputCard of [false, true]) {
        const view = describeGoalBar({
          goal: stoodDown(code),
          outcome: null,
          isRunning: false,
          hasOpenHumanInputCard,
        });
        expect(view).toMatchObject({ kind: "stopped", rawCode: null });
        if (view.kind !== "stopped") continue;
        expect(view.stop).not.toBe("unknown");
        expect(view.reasonKey).not.toBeNull();
        for (const t of [enUS, zhCN]) {
          const copy = describeGoalBarCopy(view, t);
          expect(copy?.chip).toBeTruthy();
          expect(copy?.detail).toBeTruthy();
          expect(copy?.detail).not.toContain("{");
          expect(findRawIdentifiers(copy?.detail ?? "")).toEqual([]);
        }
      }
    },
  );

  it("check-failure codes are the scheduled page's and read as unchecked", () => {
    expect(CONTRACT.check_failure_codes).toEqual([...CHECK_FAILURE_CODES]);
    for (const code of CONTRACT.check_failure_codes) {
      expect(
        describeGoalBar({
          goal: stoodDown(code),
          outcome: null,
          isRunning: false,
        }),
      ).toMatchObject({ stop: "unchecked", chip: "unchecked", note: null });
    }
  });

  it("the record keys and statuses match the frontend shape", () => {
    expect(CONTRACT.goal_outcome.channel).toBe("goal_outcome");
    expect(CONTRACT.goal_outcome.keys).toEqual([...GOAL_OUTCOME_KEYS]);
    expect(CONTRACT.history_head_keys).toContain(CONTRACT.goal_outcome.channel);
    expect(CONTRACT.history_head_keys).toContain("goal");
    const record = {
      objective: "ship it",
      goal_created_at: "",
    };
    for (const status of CONTRACT.goal_outcome.statuses) {
      expect(isThreadGoalOutcome({ ...record, status })).toBe(true);
    }
    expect(isThreadGoalOutcome({ ...record, status: "cleared" })).toBe(false);
  });

  it("host-written reasons are the ones the bar never shows as a note", () => {
    expect([...GOAL_HOST_REASON_TEXTS]).toEqual(CONTRACT.host_reason_texts);
  });
});
