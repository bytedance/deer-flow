import { afterEach, expect, test } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";

import { UsageRuns } from "@/components/workspace/usage/usage-runs";
import { enUS } from "@/core/i18n/locales/en-US";
import type { UsageRun } from "@/core/usage/types";

const run: UsageRun = {
  run_id: "run-1",
  thread_id: "thread-1",
  thread_title: "Run conversation",
  assistant_id: null,
  status: "success",
  model_name: "example-model",
  created_at: null,
  updated_at: null,
  duration_seconds: 1,
  total_tokens: 100,
  message_count: 2,
  error: null,
};

afterEach(cleanup);

function conversationLink(overrides: Partial<UsageRun>) {
  render(
    <UsageRuns
      runs={[{ ...run, ...overrides }]}
      locale="en-US"
      text={enUS.usage}
    />,
  );
  return screen
    .getByRole("link", { name: "Run conversation" })
    .getAttribute("href");
}

test.each([null, "", "lead_agent"])(
  "default assistant %s opens the normal conversation",
  (assistantId) => {
    expect(conversationLink({ assistant_id: assistantId })).toBe(
      "/workspace/chats/thread-1",
    );
  },
);

test("custom-agent runs open the matching agent conversation", () => {
  expect(conversationLink({ assistant_id: "researcher" })).toBe(
    "/workspace/agents/researcher/chats/thread-1",
  );
});

test("normalizes custom assistant aliases using the Gateway identity convention", () => {
  expect(conversationLink({ assistant_id: " Research_Agent " })).toBe(
    "/workspace/agents/research-agent/chats/thread-1",
  );
});

test.each([
  [null, "/workspace/chats/thread%2Fa%20%23%3F%25"],
  ["researcher", "/workspace/agents/researcher/chats/thread%2Fa%20%23%3F%25"],
])("encodes opaque thread ids for assistant %s", (assistantId, expected) => {
  expect(
    conversationLink({ assistant_id: assistantId, thread_id: "thread/a #?%" }),
  ).toBe(expected);
});
