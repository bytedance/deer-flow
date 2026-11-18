import { expect, it } from "@rstest/core";

import {
  isHistoryError,
  withHistoryErrorTagging,
} from "@/core/threads/history-error";

it("tags only the errors thrown by threads.getHistory", async () => {
  const historyError = new Error("HTTP 404");
  const client = {
    threads: {
      getHistory: async () => {
        throw historyError;
      },
    },
  };
  withHistoryErrorTagging(client as never);

  await expect(client.threads.getHistory()).rejects.toBe(historyError);
  expect(isHistoryError(historyError)).toBe(true);
  expect(isHistoryError(new Error("run refused"))).toBe(false);
});

it("passes a successful history read through and wraps the client once", async () => {
  const history = [{ checkpoint: { checkpoint_id: "c1" } }];
  const client = {
    threads: {
      getHistory: async () => history,
    },
  };
  withHistoryErrorTagging(client as never);
  const first = client.threads.getHistory;
  withHistoryErrorTagging(client as never);

  expect(client.threads.getHistory).toBe(first);
  await expect(client.threads.getHistory()).resolves.toBe(history);
});
