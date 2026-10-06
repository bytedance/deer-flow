import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";
import { useEffect, useRef, type RefObject } from "react";
import { toast } from "sonner";

import { GatewayApiError } from "@/core/api/errors";
import { useRenderActivity } from "@/core/dom/render-activity";
import { useI18n } from "@/core/i18n/hooks";
import type { Translations } from "@/core/i18n/locales/types";

import {
  createScheduledTask,
  deleteScheduledTask,
  fetchScheduledTask,
  fetchScheduledTasks,
  fetchThreadScheduledTasks,
  pauseScheduledTask,
  resumeScheduledTask,
  triggerScheduledTask,
  updateScheduledTask,
  type ScheduledTaskPayload,
  type ScheduledTaskUpdatePayload,
} from "./api";
import {
  describeScheduledTaskError,
  shouldReportScheduledTaskError,
} from "./errors";
import { ACTIVE_POLL_MS, IDLE_POLL_MS } from "./polling";
import {
  hasActiveRun,
  type ScheduledTask,
  type ScheduledTaskRenewal,
} from "./types";

export { ACTIVE_POLL_MS, IDLE_POLL_MS } from "./polling";

const SCHEDULED_TASKS_KEY = ["scheduled-tasks"] as const;

/** List polling: fast while any task has an active run (a recurring task stays `enabled` while it runs). */
export function scheduledTasksRefetchInterval(
  tasks: readonly ScheduledTask[] | undefined,
): number {
  return (tasks ?? []).some(hasActiveRun) ? ACTIVE_POLL_MS : IDLE_POLL_MS;
}

/** Single-task polling; off unless the consumer is on screen (`live`). */
export function scheduledTaskRefetchInterval(
  task: ScheduledTask | undefined,
  live: boolean,
): number | false {
  if (!live) {
    return false;
  }
  return task && hasActiveRun(task) ? ACTIVE_POLL_MS : IDLE_POLL_MS;
}

function isNotFound(error: unknown): boolean {
  return error instanceof GatewayApiError && error.status === 404;
}

export function useScheduledTasks() {
  return useQuery({
    queryKey: SCHEDULED_TASKS_KEY,
    queryFn: fetchScheduledTasks,
    refetchInterval: (query) => scheduledTasksRefetchInterval(query.state.data),
    refetchIntervalInBackground: false,
  });
}

export function useThreadScheduledTasks(
  threadId: string | null | undefined,
  { enabled = true }: { enabled?: boolean } = {},
) {
  return useQuery({
    queryKey: ["scheduled-tasks", "thread", threadId],
    queryFn: () => fetchThreadScheduledTasks(threadId ?? ""),
    enabled: enabled && Boolean(threadId),
    refetchInterval: (query) => scheduledTasksRefetchInterval(query.state.data),
    refetchIntervalInBackground: false,
  });
}

/**
 * One task, shared by every consumer of the same id (React Query dedupes by
 * key, so several cards of one task make one request). Polls only while
 * `live` (e.g. the card is on screen) and refetches when it becomes live
 * again. A 404 is final (no retry): the task was deleted.
 */
export function useScheduledTask(
  taskId: string | null | undefined,
  {
    enabled = true,
    initialData,
    live = true,
  }: {
    enabled?: boolean;
    initialData?: ScheduledTask;
    live?: boolean;
  } = {},
) {
  const query = useQuery({
    queryKey: ["scheduled-tasks", "task", taskId],
    queryFn: () => fetchScheduledTask(taskId ?? ""),
    enabled: enabled && Boolean(taskId),
    initialData,
    staleTime: 0,
    refetchOnMount: true,
    retry: (failureCount, error) => !isNotFound(error) && failureCount < 2,
    // A deleted task stays deleted: stop polling after a 404.
    refetchInterval: (q) =>
      isNotFound(q.state.error)
        ? false
        : scheduledTaskRefetchInterval(q.state.data, live),
    refetchIntervalInBackground: false,
  });
  const { refetch } = query;
  const wasLive = useRef(live);
  useEffect(() => {
    if (live && !wasLive.current && enabled && taskId) {
      void refetch();
    }
    wasLive.current = live;
  }, [enabled, live, refetch, taskId]);
  return query;
}

/** True while the element is on screen (and the page is visible). */
export function useInView(ref: RefObject<Element | null>): boolean {
  return useRenderActivity(ref, false, false);
}

function invalidateScheduledTasks(queryClient: QueryClient) {
  // The prefix covers the list, thread lists, single tasks and run history.
  void queryClient.invalidateQueries({ queryKey: SCHEDULED_TASKS_KEY });
}

function useErrorToast(action: keyof Translations["scheduledTasks"]["errors"]) {
  const { t, locale } = useI18n();
  return (error: Error) => {
    if (!shouldReportScheduledTaskError(error)) {
      return;
    }
    const { message } = describeScheduledTaskError(error, t, { locale });
    toast.error(`${t.scheduledTasks.errors[action]}: ${message}`);
  };
}

export function useCreateScheduledTask() {
  const queryClient = useQueryClient();
  const onError = useErrorToast("create");
  return useMutation({
    mutationFn: (payload: ScheduledTaskPayload) => createScheduledTask(payload),
    onSuccess: () => invalidateScheduledTasks(queryClient),
    onError,
  });
}

export function useUpdateScheduledTask(taskId: string) {
  const queryClient = useQueryClient();
  const onError = useErrorToast("update");
  return useMutation({
    mutationFn: (payload: ScheduledTaskUpdatePayload) =>
      updateScheduledTask(taskId, payload),
    onSuccess: () => invalidateScheduledTasks(queryClient),
    onError,
  });
}

export function usePauseScheduledTask() {
  const queryClient = useQueryClient();
  const onError = useErrorToast("pause");
  return useMutation({
    mutationFn: (taskId: string) => pauseScheduledTask(taskId),
    onSuccess: () => invalidateScheduledTasks(queryClient),
    onError,
  });
}

export function useResumeScheduledTask({
  toastOnError = true,
}: {
  /** False when the caller handles errors itself (e.g. `limits_exhausted` opens the renew dialog). */
  toastOnError?: boolean;
} = {}) {
  const queryClient = useQueryClient();
  const onError = useErrorToast("resume");
  return useMutation({
    mutationFn: ({
      taskId,
      renewal,
    }: {
      taskId: string;
      renewal?: ScheduledTaskRenewal;
    }) => resumeScheduledTask(taskId, renewal),
    onSuccess: () => invalidateScheduledTasks(queryClient),
    onError: toastOnError ? onError : undefined,
  });
}

export function useTriggerScheduledTask() {
  const queryClient = useQueryClient();
  const onError = useErrorToast("trigger");
  return useMutation({
    mutationFn: (taskId: string) => triggerScheduledTask(taskId),
    onSuccess: () => invalidateScheduledTasks(queryClient),
    onError,
  });
}

export function useDeleteScheduledTask() {
  const queryClient = useQueryClient();
  const onError = useErrorToast("delete");
  return useMutation({
    mutationFn: (taskId: string) => deleteScheduledTask(taskId),
    onSuccess: () => invalidateScheduledTasks(queryClient),
    onError,
  });
}
