import { expect, it } from "@rstest/core";

import {
  markThreadCreation,
  takeRequestedThreadId,
  withThreadCreationTagging,
} from "@/core/threads/thread-creation";

it("records the submission that asked for a created thread, once", () => {
  markThreadCreation("server-a", "placeholder-a");
  expect(takeRequestedThreadId("server-a")).toBe("placeholder-a");
  // Read once: a second report for the same id is not this send's.
  expect(takeRequestedThreadId("server-a")).toBeUndefined();
  expect(takeRequestedThreadId("server-unknown")).toBeUndefined();
});

it("records a create that carried a submission id and passes it through", async () => {
  const created = { thread_id: "server-b" };
  const client = {
    threads: {
      create: async (payload?: { threadId?: string }) => ({
        ...created,
        thread_id: payload?.threadId ? "server-b" : "server-c",
      }),
    },
  };
  withThreadCreationTagging(client as never);

  await expect(
    client.threads.create({ threadId: "placeholder-b" }),
  ).resolves.toEqual({ thread_id: "server-b" });
  expect(takeRequestedThreadId("server-b")).toBe("placeholder-b");

  // A create without a submission id records nothing, so the hook falls back
  // to submission order.
  await client.threads.create({});
  expect(takeRequestedThreadId("server-c")).toBeUndefined();
});
