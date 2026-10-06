import { readFileSync } from "node:fs";

import type { Locator, Page } from "@playwright/test";

import type {
  MockScheduledTask,
  MockScheduledTaskRun,
  MockThread,
} from "./mock-api";

/**
 * Recorded takes (ux-audit evidence en-3 / zh-1): the task and runs as the
 * page reads them, and the origin chat and one run conversation shaped by
 * the PR1 contracts (see each file's `_provenance`).
 */
function fixture<T>(name: string): T {
  return JSON.parse(
    readFileSync(
      new URL(`../fixtures/scheduled/${name}`, import.meta.url),
      "utf8",
    ),
  ) as T;
}

export type ScheduledTake = {
  lang: "en" | "zh";
  task: MockScheduledTask;
  runs: MockScheduledTaskRun[];
  chatThread: MockThread;
  runThread: MockThread;
};

export function scheduledTake(take: "en-3" | "zh-1"): ScheduledTake {
  return {
    lang: take === "en-3" ? "en" : "zh",
    task: fixture<MockScheduledTask>(`${take}-task.json`),
    runs: fixture<MockScheduledTaskRun[]>(`${take}-runs.json`),
    chatThread: fixture<MockThread>(`${take}-chat-thread.json`),
    runThread: fixture<MockThread>(`${take}-run-thread.json`),
  };
}

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
