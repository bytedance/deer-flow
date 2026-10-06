import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import type { Message } from "@langchain/langgraph-sdk";

import type {
  ScheduledTask,
  ScheduledTaskRun,
} from "@/core/scheduled-tasks/types";

/**
 * Live-recorded chat / run-thread fixtures shared with the Playwright specs
 * (`tests/e2e/fixtures/scheduled/live-*.json`, recorded on DeepSeek Flash
 * during the PR1 acceptance run; demo data, fictional names):
 * - `weekday-chat`: create (after a read_file), trial, edit, pause, resume;
 * - `minute-chat`: create a per-minute task (after a read_file);
 * - `minute-run`: scheduled run 2, which reads the file and stops the task.
 */
export type ScheduledThreadFixture = {
  thread_id: string;
  title: string;
  updated_at: string;
  messages: Message[];
};

const LIVE_THREADS = {
  "weekday-chat": ["live-weekday.json", "chatThread"],
  "minute-chat": ["live-minute.json", "chatThread"],
  "minute-run": ["live-minute.json", "runThread"],
} as const;

function liveBundle(file: string): Record<string, unknown> {
  return JSON.parse(
    readFileSync(
      resolve(__dirname, `../../e2e/fixtures/scheduled/${file}`),
      "utf-8",
    ),
  ) as Record<string, unknown>;
}

/** The live per-minute task (paused by its agent in run 2) and its runs, newest first. */
export function loadLiveMinuteTask(): {
  task: ScheduledTask;
  runs: ScheduledTaskRun[];
} {
  const bundle = liveBundle("live-minute.json");
  return {
    task: bundle.task as ScheduledTask,
    runs: bundle.runs as ScheduledTaskRun[],
  };
}

export function loadScheduledThread(
  name: keyof typeof LIVE_THREADS,
): ScheduledThreadFixture {
  const [file, key] = LIVE_THREADS[name];
  return liveBundle(file)[key] as ScheduledThreadFixture;
}

export const SCHEDULED_GOAL_NOTES_CONTRACT = JSON.parse(
  readFileSync(
    resolve(
      __dirname,
      "../../../../contracts/scheduled_goal_notes_contract.json",
    ),
    "utf-8",
  ),
) as { scheduled_origin_key: string };

/**
 * The same thread with the scheduled launch turned into an ordinary user
 * message, for "behaves like a normal turn" comparisons.
 */
export function withOrdinaryHumanTurn(messages: Message[]): Message[] {
  return messages.map((message) =>
    message.type === "human"
      ? ({
          ...message,
          content: "Check the checklist",
          additional_kwargs: {},
        } as Message)
      : message,
  );
}
