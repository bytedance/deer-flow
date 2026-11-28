import { expect, it } from "@rstest/core";

import { runErrorThreadId } from "@/core/threads/run-error";
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

it("tags a refused create with the submission that asked for the thread", async () => {
  const refusal = new Error("422 Unprocessable Entity");
  const client = {
    threads: {
      create: async (payload?: { threadId?: string }) => {
        if (payload?.threadId === "placeholder-refused") throw refusal;
        return { thread_id: "server-ok" };
      },
    },
  };
  withThreadCreationTagging(client as never);

  await expect(
    client.threads.create({ threadId: "placeholder-refused" }),
  ).rejects.toBe(refusal);
  // The SDK reports this refusal through `onError` without run metadata, so the
  // tag is the only identity the hook can settle it with; without it the
  // fallback rejects whichever send is mounted when the refusal surfaces.
  expect(runErrorThreadId(refusal)).toBe("placeholder-refused");

  // A create that carried no submission id stays untagged for the fallback.
  const anonymous = new Error("create without an id");
  const anonymousClient = {
    threads: {
      create: async () => {
        throw anonymous;
      },
    },
  };
  withThreadCreationTagging(anonymousClient as never);
  await expect(anonymousClient.threads.create()).rejects.toBe(anonymous);
  expect(runErrorThreadId(anonymous)).toBeUndefined();
});
