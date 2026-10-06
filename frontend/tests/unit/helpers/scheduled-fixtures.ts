import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import type { Message } from "@langchain/langgraph-sdk";

/**
 * Recorded chat / run-thread fixtures shared with the Playwright specs
 * (`tests/e2e/fixtures/scheduled/*-thread.json`).
 */
export type ScheduledThreadFixture = {
  thread_id: string;
  title: string;
  updated_at: string;
  messages: Message[];
};

export function loadScheduledThread(
  name:
    | "en-3-chat-thread"
    | "zh-1-chat-thread"
    | "en-3-run-thread"
    | "zh-1-run-thread",
): ScheduledThreadFixture {
  return JSON.parse(
    readFileSync(
      resolve(__dirname, `../../e2e/fixtures/scheduled/${name}.json`),
      "utf-8",
    ),
  ) as ScheduledThreadFixture;
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
