import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "@rstest/core";

import { enUS } from "@/core/i18n/locales/en-US";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import {
  describeRunError,
  HOST_RUN_ERRORS,
} from "@/core/scheduled-tasks/run-error";
import type { ScheduledTaskRun } from "@/core/scheduled-tasks/types";

type ContractFile = { host_run_errors: Record<string, string> };

const CONTRACT = JSON.parse(
  readFileSync(
    resolve(
      __dirname,
      "../../../../../contracts/scheduled_goal_notes_contract.json",
    ),
    "utf-8",
  ),
) as ContractFile;

type RunInput = Pick<ScheduledTaskRun, "status" | "error" | "run_id">;
const run = (overrides: Partial<RunInput>): RunInput => ({
  status: "failed",
  error: null,
  run_id: "run-1",
  ...overrides,
});

const CONTRACT_KEYS: Record<string, string> = {
  restarted: "restarted",
  lease_lost: "leaseLost",
  queue_timeout: "queueTimeout",
  paused_while_queued: "pausedWhileQueued",
  deleted_while_queued: "deletedWhileQueued",
  end_reached: "endReached",
  interrupted: "interrupted",
};

describe("describeRunError", () => {
  it("knows exactly the contract's host-written run errors", () => {
    expect(Object.keys(HOST_RUN_ERRORS).sort()).toEqual(
      Object.values(CONTRACT.host_run_errors).sort(),
    );
  });

  it.each(Object.entries(CONTRACT.host_run_errors))(
    "host error %s maps to its own copy",
    (name, text) => {
      const key = CONTRACT_KEYS[name];
      const described = describeRunError(
        run({ status: "interrupted", error: text, run_id: null }),
      );
      expect(described).toEqual({ key, raw: null });
      expect(
        enUS.scheduledTasks.runErrors[
          key as keyof typeof enUS.scheduledTasks.runErrors
        ],
      ).toBeTruthy();
      expect(
        zhCN.scheduledTasks.runErrors[
          key as keyof typeof zhCN.scheduledTasks.runErrors
        ],
      ).toMatch(/[一-鿿]/);
    },
  );

  it("a queue timeout without an agent run is a skip, not a launch failure", () => {
    expect(
      describeRunError(
        run({
          status: "failed",
          error: CONTRACT.host_run_errors.queue_timeout,
          run_id: null,
        }),
      )?.key,
    ).toBe("queueTimeout");
  });

  it("a failed row that never got an agent run failed to start", () => {
    expect(
      describeRunError(
        run({ status: "failed", error: "model not configured", run_id: null }),
      ),
    ).toEqual({ key: "launchFailed", raw: "model not configured" });
  });

  it("an unknown failure keeps its raw text for Details", () => {
    expect(describeRunError(run({ status: "failed", error: "boom" }))).toEqual({
      key: "failed",
      raw: "boom",
    });
    expect(describeRunError(run({ status: "failed" }))).toEqual({
      key: "failed",
      raw: null,
    });
    expect(
      describeRunError(run({ status: "interrupted", error: "cancelled" })),
    ).toEqual({ key: "interrupted", raw: "cancelled" });
  });

  it("successes, goal outcomes and runs in progress have no run error", () => {
    for (const status of [
      "success",
      "unmet",
      "queued",
      "launching",
      "running",
    ] as const) {
      expect(describeRunError(run({ status, error: null }))).toBeNull();
    }
    expect(
      describeRunError(run({ status: "unmet", error: "evaluator_failed" })),
    ).toBeNull();
  });
});
