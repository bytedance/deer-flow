import { expect, it } from "@rstest/core";

import { tagThreadClient } from "@/core/threads/client";
import { isHistoryError } from "@/core/threads/history-error";
import { runErrorThreadId } from "@/core/threads/run-error";

it("tags refused runs, refused creates and failed history reads", async () => {
  const runError = new Error("run refused");
  const createError = new Error("create refused");
  const historyError = new Error("history failed");
  const client = {
    runs: {
      async *stream(..._args: unknown[]) {
        throw runError;
      },
    },
    threads: {
      async create(_payload?: { threadId?: string }) {
        throw createError;
      },
      async getHistory(..._args: unknown[]) {
        throw historyError;
      },
    },
  };
  tagThreadClient(client as never);

  // The SDK reports all three through `onError` without run metadata; each
  // wrapper must record the identity its own call site knows.
  await expect(
    (async () => {
      for await (const _chunk of client.runs.stream("thread-run")) {
        void _chunk;
      }
    })(),
  ).rejects.toBe(runError);
  expect(runErrorThreadId(runError)).toBe("thread-run");

  await expect(
    client.threads.create({ threadId: "placeholder-create" }),
  ).rejects.toBe(createError);
  expect(runErrorThreadId(createError)).toBe("placeholder-create");

  await expect(client.threads.getHistory("thread-history")).rejects.toBe(
    historyError,
  );
  expect(isHistoryError(historyError)).toBe(true);
});
