import type { Message } from "@langchain/langgraph-sdk";
import { expect, test } from "vitest";

import {
  formatThreadAsJSON,
  formatThreadAsMarkdown,
} from "@/core/threads/export";
import type { AgentThread } from "@/core/threads/types";

const thread = {
  thread_id: "thread-1",
  created_at: "2026-05-11T00:00:00.000Z",
  values: { title: "Export test" },
} as AgentThread;

test("omits hidden summary messages from markdown export", () => {
  const messages = [
    {
      id: "summary-1",
      type: "human",
      name: "summary",
      content: "Here is a summary of the conversation to date...",
    },
    {
      id: "human-1",
      type: "human",
      content: "What happened?",
    },
    {
      id: "ai-1",
      type: "ai",
      content: "Only visible messages are exported.",
    },
  ] as Message[];

  const markdown = formatThreadAsMarkdown(thread, messages);

  expect(markdown).toContain("What happened?");
  expect(markdown).toContain("Only visible messages are exported.");
  expect(markdown).not.toContain("Here is a summary of the conversation");
});

test("omits hidden summary messages from json export", () => {
  const messages = [
    {
      id: "summary-1",
      type: "human",
      name: "summary",
      content: "Here is a summary of the conversation to date...",
    },
    {
      id: "human-1",
      type: "human",
      content: "Visible message",
    },
  ] as Message[];

  const json = JSON.parse(formatThreadAsJSON(thread, messages)) as {
    messages: Array<{ id: string }>;
  };

  expect(json.messages.map((message) => message.id)).toEqual(["human-1"]);
});
