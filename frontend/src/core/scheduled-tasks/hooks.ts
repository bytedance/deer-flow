import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createScheduledTask,
  deleteScheduledTask,
  fetchScheduledTaskRuns,
  fetchScheduledTasks,
  fetchThreadScheduledTasks,
  pauseScheduledTask,
  resumeScheduledTask,
  triggerScheduledTask,
  updateScheduledTask,
  type ScheduledTaskPayload,
} from "./api";

export function useScheduledTasks() {
  return useQuery({
    queryKey: ["scheduled-tasks"],
    queryFn: fetchScheduledTasks,
  });
}

export function useThreadScheduledTasks(threadId: string | null | undefined) {
  return useQuery({
    queryKey: ["scheduled-tasks", "thread", threadId],
    queryFn: () => fetchThreadScheduledTasks(threadId ?? ""),
    enabled: Boolean(threadId),
  });
}

export function useScheduledTaskRuns(taskId: string | null | undefined) {
  return useQuery({
    queryKey: ["scheduled-tasks", "runs", taskId],
    queryFn: () => fetchScheduledTaskRuns(taskId ?? ""),
    enabled: Boolean(taskId),
  });
}

export function useCreateScheduledTask() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: ScheduledTaskPayload) => createScheduledTask(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["scheduled-tasks"] });
    },
  });
}

export function useUpdateScheduledTask(taskId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (
      payload: Partial<
        Omit<ScheduledTaskPayload, "thread_id" | "schedule_type">
      >,
    ) => updateScheduledTask(taskId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["scheduled-tasks"] });
      void queryClient.invalidateQueries({
        queryKey: ["scheduled-tasks", "thread"],
      });
    },
  });
}

export function usePauseScheduledTask() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (taskId: string) => pauseScheduledTask(taskId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["scheduled-tasks"] });
      void queryClient.invalidateQueries({
        queryKey: ["scheduled-tasks", "thread"],
      });
    },
  });
}

export function useResumeScheduledTask() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (taskId: string) => resumeScheduledTask(taskId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["scheduled-tasks"] });
      void queryClient.invalidateQueries({
        queryKey: ["scheduled-tasks", "thread"],
      });
    },
  });
}

export function useTriggerScheduledTask() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (taskId: string) => triggerScheduledTask(taskId),
    onSuccess: (_result, taskId) => {
      void queryClient.invalidateQueries({ queryKey: ["scheduled-tasks"] });
      void queryClient.invalidateQueries({
        queryKey: ["scheduled-tasks", "thread"],
      });
      void queryClient.invalidateQueries({
        queryKey: ["scheduled-tasks", "runs", taskId],
      });
    },
  });
}

export function useDeleteScheduledTask() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (taskId: string) => deleteScheduledTask(taskId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["scheduled-tasks"] });
      void queryClient.invalidateQueries({
        queryKey: ["scheduled-tasks", "thread"],
      });
    },
  });
}
