import { readFileSync } from "node:fs";

import type { Locator, Page } from "@playwright/test";

import type {
  MockScheduledTask,
  MockScheduledTaskRun,
  MockThread,
} from "./mock-api";

/**
 * Live-recorded takes from the PR1 acceptance run on DeepSeek Flash (demo
 * data, fictional names; see each file's `_provenance`):
 * - `minute`: a zh chat creates a per-minute checklist task; run 1 finds two
 *   open items, run 2 finds the list done and the agent pauses the task.
 * - `weekday`: a zh chat creates a weekday task, runs a trial, moves it to
 *   daily 10:00, pauses and resumes it, all on the same task.
 * The conversations are Chinese; specs run the UI in both locales over them.
 */
export type LiveTake = {
  task: MockScheduledTask;
  runs: MockScheduledTaskRun[];
  chatThread: MockThread;
  runThread?: MockThread;
};

export function liveTake(take: "minute" | "weekday"): LiveTake {
  const { task, runs, chatThread, runThread } = JSON.parse(
    readFileSync(
      new URL(`../fixtures/scheduled/live-${take}.json`, import.meta.url),
      "utf8",
    ),
  ) as LiveTake;
  return { task, runs, chatThread, ...(runThread ? { runThread } : {}) };
}

/** The live minute take with its run conversation, which it always has. */
export function liveMinuteTake(): LiveTake & { runThread: MockThread } {
  const take = liveTake("minute");
  if (!take.runThread) {
    throw new Error("live-minute.json has no runThread");
  }
  return take as LiveTake & { runThread: MockThread };
}

export const LOCALES = ["en", "zh"] as const;

export async function setLocaleCookie(page: Page, lang: "en" | "zh") {
  await page.context().addCookies([
    {
      name: "locale",
      value: lang === "zh" ? "zh-CN" : "en-US",
      url: "http://localhost:3000",
    },
  ]);
}

/** The open chat's message area (excludes the sidebar's thread titles). */
export function conversation(page: Page): Locator {
  return page.locator(
    '[data-testid^="workspace-chats-"][data-testid$="-chat"] main',
  );
}
