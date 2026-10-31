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

/** One history page, plus one run to tell whether an older page exists. */
function runPageQuery(taskId: string | undefined, page: number) {
  return {
    queryKey: ["scheduled-tasks", "runs", taskId, page],
    queryFn: ({ signal }: { signal: AbortSignal }) =>
      fetchScheduledTaskRuns(taskId ?? "", {
        limit: RUN_HISTORY_PAGE_SIZE + 1,
        offset: page * RUN_HISTORY_PAGE_SIZE,
        signal,
      }),
    enabled: Boolean(taskId),
  };
}

/**
 * The newest runs (the latest history page) whichever page the history
 * shows, for what describes the task's current state. It shares the latest
 * page's cache entry and leaves refreshing to the history, which refreshes
 * the latest page only while it is shown: an older page triggers no request.
 */
export function useLatestScheduledTaskRuns(
  taskId: string | undefined,
): readonly ScheduledTaskRun[] {
  const { data } = useQuery({
    ...runPageQuery(taskId, 0),
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
  return data?.slice(0, RUN_HISTORY_PAGE_SIZE) ?? NO_RUNS;
}

const NO_RUNS: readonly ScheduledTaskRun[] = [];

export function useScheduledTaskRunHistory(taskId: string | undefined) {
  const client = useQueryClient();
  const [position, setPosition] = useState({ taskId, page: 0 });
  const page = position.taskId === taskId ? position.page : 0;
  if (position.taskId !== taskId) {
    setPosition({ taskId, page: 0 });
  }
  const query = useQuery({
    ...runPageQuery(taskId, page),
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
