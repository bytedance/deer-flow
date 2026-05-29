import { useQuery } from "@tanstack/react-query";

import { getBudgetStatus, type BudgetStatus } from "./api";

export function useBudgetStatus() {
  return useQuery<BudgetStatus>({
    queryKey: ["budget-status"],
    queryFn: getBudgetStatus,
    refetchInterval: 60_000, // Refresh every minute
    staleTime: 30_000, // Consider stale after 30 seconds
  });
}
