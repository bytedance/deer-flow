import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { fetchScheduledTaskRuns } from "./api";

export const RUN_HISTORY_PAGE_SIZE = 50;

export function useScheduledTaskRunHistory(taskId: string | undefined) {
  const client = useQueryClient();
  const [position, setPosition] = useState({ taskId, page: 0 });
  const page = position.taskId === taskId ? position.page : 0;
  if (position.taskId !== taskId) {
    setPosition({ taskId, page: 0 });
  }
  const query = useQuery({
    queryKey: ["scheduled-tasks", "runs", taskId, page],
    queryFn: ({ signal }) =>
      fetchScheduledTaskRuns(taskId ?? "", {
        limit: RUN_HISTORY_PAGE_SIZE + 1,
        offset: page * RUN_HISTORY_PAGE_SIZE,
        signal,
      }),
    enabled: Boolean(taskId),
    refetchInterval: page === 0 ? 15000 : false,
    refetchIntervalInBackground: false,
    refetchOnMount: page === 0,
    refetchOnWindowFocus: page === 0,
    refetchOnReconnect: page === 0,
  });
  return {
    ...query,
    data: query.data?.slice(0, RUN_HISTORY_PAGE_SIZE),
    page,
    hasOlder: (query.data?.length ?? 0) > RUN_HISTORY_PAGE_SIZE,
    older: () => setPosition({ taskId, page: page + 1 }),
    newer: () => setPosition({ taskId, page: Math.max(0, page - 1) }),
    latest: () => {
      setPosition({ taskId, page: 0 });
      void client.invalidateQueries({
        queryKey: ["scheduled-tasks", "runs", taskId, 0],
        exact: true,
      });
    },
  };
}
