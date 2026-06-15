import { useQueryClient } from "@tanstack/react-query";

import type { AgentThread } from "./types";

export function useHasActiveRun(threadId: string | null | undefined): boolean {
  const queryClient = useQueryClient();

  if (!threadId) return false;

  const thread = queryClient.getQueryData<AgentThread>(["thread", threadId]);
  if (thread?.status === "busy" || thread?.status === "interrupted") return true;

  const threads = queryClient.getQueriesData<AgentThread[]>({
    queryKey: ["threads", "search"],
  });
  return threads.some(([, data]) =>
    data?.some(
      (t) =>
        t.thread_id === threadId &&
        (t.status === "busy" || t.status === "interrupted"),
    ),
  );
}
