import { useQuery } from "@tanstack/react-query";

import { fetchWorkflowTraceByRun } from "./api";

export function useWorkflowTraceByRun(
  runId?: string | null,
  { enabled = true }: { enabled?: boolean } = {},
) {
  return useQuery({
    queryKey: ["workflow-trace", "run", runId],
    queryFn: () => {
      if (!runId) {
        return null;
      }
      return fetchWorkflowTraceByRun(runId);
    },
    enabled: enabled && Boolean(runId),
    refetchOnWindowFocus: false,
  });
}
