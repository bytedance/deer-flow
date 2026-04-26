/**
 * Canvas React hooks，用于状态管理。
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  deleteCanvas,
  executeCanvas,
  getCanvas,
  getComponents,
  getExecutionStatus,
  updateCanvas,
} from "./api";
import type { CanvasExecuteRequest, CanvasUpdateRequest } from "./types";

/**
 * 获取线程 canvas 的 hook。
 */
export function useCanvas(threadId: string, enabled = true) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["canvas", threadId],
    queryFn: () => getCanvas(threadId),
    enabled: enabled && !!threadId,
    staleTime: 30 * 1000, // 30 秒
  });

  return {
    canvas: data,
    isLoading,
    error,
    refetch,
  };
}

/**
 * 更新 canvas 的 hook。
 */
export function useUpdateCanvas(threadId: string) {
  const queryClient = useQueryClient();

  const { mutate, mutateAsync, isPending, error } = useMutation({
    mutationFn: (request: CanvasUpdateRequest) => updateCanvas(threadId, request),
    onSuccess: (canvas) => {
      queryClient.setQueryData(["canvas", threadId], canvas);
    },
  });

  return {
    updateCanvas: mutate,
    updateCanvasAsync: mutateAsync,
    isUpdating: isPending,
    error,
  };
}

/**
 * 执行 canvas 的 hook。
 */
export function useExecuteCanvas(threadId: string) {
  const queryClient = useQueryClient();

  const { mutate, mutateAsync, isPending, error } = useMutation({
    mutationFn: (request?: CanvasExecuteRequest) => executeCanvas(threadId, request),
    onSuccess: () => {
      // 使 canvas 缓存失效以获取更新后的状态
      queryClient.invalidateQueries({ queryKey: ["canvas", threadId] });
      queryClient.invalidateQueries({ queryKey: ["canvas-status", threadId] });
    },
  });

  return {
    executeCanvas: mutate,
    executeCanvasAsync: mutateAsync,
    isExecuting: isPending,
    error,
  };
}

/**
 * 获取执行状态的 hook。
 */
export function useExecutionStatus(threadId: string, enabled = false) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["canvas-status", threadId],
    queryFn: () => getExecutionStatus(threadId),
    enabled: enabled && !!threadId,
    refetchInterval: enabled ? 2000 : false, // 启用时每 2 秒轮询
  });

  return {
    status: data,
    isLoading,
    error,
    refetch,
  };
}

/**
 * 删除 canvas 的 hook。
 */
export function useDeleteCanvas(threadId: string) {
  const queryClient = useQueryClient();

  const { mutate, mutateAsync, isPending, error } = useMutation({
    mutationFn: () => deleteCanvas(threadId),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: ["canvas", threadId] });
      queryClient.removeQueries({ queryKey: ["canvas-status", threadId] });
    },
  });

  return {
    deleteCanvas: mutate,
    deleteCanvasAsync: mutateAsync,
    isDeleting: isPending,
    error,
  };
}

/**
 * 获取可用组件的 hook。
 */
export function useComponents(enabled = true) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["canvas-components"],
    queryFn: getComponents,
    enabled,
    staleTime: 5 * 60 * 1000, // 5 分钟
  });

  return {
    components: data?.components ?? [],
    isLoading,
    error,
  };
}
