import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { useI18n } from "@/core/i18n/hooks";

import {
  cancelBackgroundTask,
  fetchBackgroundTask,
  fetchBackgroundTasks,
} from "./api";
import {
  isActiveBackgroundTask,
  shouldPollBackgroundTaskDetail,
} from "./types";

export const backgroundTasksQueryKey = (threadId: string) =>
  ["background-tasks", threadId] as const;

export const backgroundTaskQueryKey = (threadId: string, taskId: string) =>
  [...backgroundTasksQueryKey(threadId), taskId] as const;

export function useBackgroundTasks(
  threadId: string,
  options: { enabled?: boolean } = {},
) {
  return useQuery({
    queryKey: backgroundTasksQueryKey(threadId),
    queryFn: () => fetchBackgroundTasks(threadId),
    enabled: options.enabled !== false && Boolean(threadId),
    refetchInterval: (query) =>
      query.state.data?.some(isActiveBackgroundTask) ? 3000 : 15000,
    refetchIntervalInBackground: false,
  });
}

export function useBackgroundTask(
  threadId: string,
  taskId: string,
  options: { enabled?: boolean } = {},
) {
  return useQuery({
    queryKey: backgroundTaskQueryKey(threadId, taskId),
    queryFn: () => fetchBackgroundTask(threadId, taskId),
    enabled: options.enabled !== false && Boolean(threadId) && Boolean(taskId),
    refetchInterval: (query) =>
      query.state.data && shouldPollBackgroundTaskDetail(query.state.data)
        ? 3000
        : false,
    refetchIntervalInBackground: false,
  });
}

export function useCancelBackgroundTask(threadId: string) {
  const queryClient = useQueryClient();
  const { t } = useI18n();
  return useMutation({
    mutationFn: (taskId: string) => cancelBackgroundTask(threadId, taskId),
    onSuccess: async (task) => {
      // This thread's task list and detail reads poll the same caches the
      // confirmation is about to seed. A read that started before the cancel
      // answered must not land afterwards and put the card back to "working"
      // (#7177); same ordering contract as the memory mutations (#6959).
      await queryClient.cancelQueries({
        queryKey: backgroundTasksQueryKey(threadId),
      });
      queryClient.setQueryData(
        backgroundTaskQueryKey(threadId, task.task_id),
        task,
      );
      queryClient.setQueryData(
        backgroundTasksQueryKey(threadId),
        (current: unknown) =>
          Array.isArray(current)
            ? current.map((item) =>
                typeof item === "object" &&
                item !== null &&
                "task_id" in item &&
                item.task_id === task.task_id
                  ? task
                  : item,
              )
            : current,
      );
      void queryClient.invalidateQueries({
        queryKey: backgroundTasksQueryKey(threadId),
      });
    },
    onError: (error: Error) => {
      toast.error(`${t.backgroundTasks.cancelFailed}: ${error.message}`);
    },
  });
}
