import { expect, test } from "@rstest/core";
import { QueryClient, QueryObserver } from "@tanstack/react-query";

import {
  deriveHitlApprovalState,
  invalidateStoppedThreadCaches,
} from "@/core/threads/hooks";
import { approvalsKey } from "@/core/threads/tool-approvals";

test("terminal invalidation reconciles pending child approvals in the current thread", async () => {
  const client = new QueryClient();
  const key = approvalsKey("thread", "owner");
  const other = approvalsKey("other-thread", "owner");
  client.setQueryData(key, { requests: [{ request_id: "child" }] });
  client.setQueryData(other, { requests: [{ request_id: "other" }] });
  let fetches = 0;
  const observer = new QueryObserver(client, {
    queryKey: key,
    staleTime: Infinity,
    queryFn: async () => {
      fetches += 1;
      return { requests: [] };
    },
  });
  const unsubscribe = observer.subscribe(() => undefined);
  invalidateStoppedThreadCaches(client, "thread", false);
  await client.refetchQueries({ queryKey: key, stale: true });
  expect(client.getQueryData(key)).toEqual({ requests: [] });
  expect(fetches).toBeGreaterThan(0);
  expect(client.getQueryState(other)?.isInvalidated).toBe(false);
  unsubscribe();
  client.clear();
});

test("a server-owned pending approval run supports degraded tools-node pauses", () => {
  const args = {
    liveInterrupt: undefined,
    historyLoading: true,
    answeredRequestIds: new Set<string>(),
    next: ["tools"],
  };
  expect(
    deriveHitlApprovalState({ ...args, pendingApprovalRun: true })
      .hasPendingApproval,
  ).toBe(true);
  expect(deriveHitlApprovalState(args).hasPendingApproval).toBe(false);
});
