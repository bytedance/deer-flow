import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { fetchScheduledTaskRuns } from "./api";
import { ACTIVE_POLL_MS, IDLE_POLL_MS } from "./polling";
import type { ScheduledTaskRun } from "./types";

export const RUN_HISTORY_PAGE_SIZE = 50;

const ACTIVE_RUN_STATUSES: ReadonlySet<ScheduledTaskRun["status"]> = new Set([
  "queued",
  "launching",
  "running",
]);

export function isActiveRun(run: Pick<ScheduledTaskRun, "status">): boolean {
  return ACTIVE_RUN_STATUSES.has(run.status);
}

/** Only the latest page polls: fast while a loaded run is queued, starting or running. */
export function runHistoryRefetchInterval(
  runs: readonly ScheduledTaskRun[] | undefined,
  page: number,
): number | false {
  if (page !== 0) {
    return false;
  }
  return (runs ?? []).some(isActiveRun) ? ACTIVE_POLL_MS : IDLE_POLL_MS;
}

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
    refetchInterval: (q) => runHistoryRefetchInterval(q.state.data, page),
    refetchIntervalInBackground: false,
    refetchOnMount: page === 0,
    refetchOnWindowFocus: page === 0,
    refetchOnReconnect: page === 0,
  });

  // When a run that was active on the latest page has finished, the task
  // itself changed too (status, last run, runs used): refresh task queries.
  const activeRuns = useRef<{ taskId: string | undefined; ids: Set<string> }>({
    taskId,
    ids: new Set(),
  });
  const { data } = query;
  useEffect(() => {
    if (page !== 0 || !data) {
      return;
    }
    const previous =
      activeRuns.current.taskId === taskId
        ? activeRuns.current.ids
        : new Set<string>();
    const finished = data.some(
      (run) => previous.has(run.id) && !isActiveRun(run),
    );
    activeRuns.current = {
      taskId,
      ids: new Set(data.filter(isActiveRun).map((run) => run.id)),
    };
    if (finished) {
      void client.invalidateQueries({
        queryKey: ["scheduled-tasks"],
        predicate: (q) => q.queryKey[1] !== "runs",
      });
    }
  }, [client, data, page, taskId]);

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
