import { expect, it } from "@rstest/core";

import { runErrorThreadId, withRunErrorTagging } from "@/core/threads/run-error";

it("tags the refusal a run stream throws with the thread it was sent to", async () => {
  const refusal = new Error("HTTP 422");
  const client = {
    runs: {
      stream: async function* (_threadId: string) {
        throw refusal;
      },
    },
  };
  withRunErrorTagging(client as never);

  const iterate = async () => {
    for await (const chunk of client.runs.stream("thread-1" as never)) {
      void chunk;
    }
  };
  await expect(iterate()).rejects.toBe(refusal);
  expect(runErrorThreadId(refusal)).toBe("thread-1");
  expect(runErrorThreadId(new Error("run refused"))).toBeUndefined();
});

it("passes a stream through and wraps the client once", async () => {
  const chunks = [{ event: "metadata" }, { event: "end" }];
  const client = {
    runs: {
      stream: async function* (_threadId: string) {
        yield* chunks;
      },
    },
  };
  const wrapped = withRunErrorTagging(client as never);
  expect(wrapped).toBe(client);

  const seen: unknown[] = [];
  for await (const chunk of client.runs.stream("thread-1" as never)) {
    seen.push(chunk);
  }
  expect(seen).toEqual(chunks);
});
