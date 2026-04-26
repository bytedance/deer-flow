/**
 * Canvas React hooks，用于状态管理。
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  deleteCanvas,
  executeCanvas,
  getCanvas,
  getComponents,
  getDbConnections,
  getExecutionStatus,
  getTableSchema,
  getTables,
  previewNodeOutput,
  previewTable,
  stopCanvasExecution,
  updateCanvas,
  validateSQL,
} from "./api";
import type {
  CanvasExecuteRequest,
  CanvasUpdateRequest,
  ValidateSQLRequest,
} from "./types";

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
      void queryClient.invalidateQueries({ queryKey: ["canvas", threadId] });
      void queryClient.invalidateQueries({ queryKey: ["canvas-status", threadId] });
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

/**
 * 获取数据库连接列表的 hook。
 */
export function useDbConnections(enabled = true) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["db-connections"],
    queryFn: getDbConnections,
    enabled,
    staleTime: 5 * 60 * 1000, // 5 分钟
  });

  return {
    connections: data?.connections ?? [],
    isLoading,
    error,
  };
}

/**
 * 获取表列表的 hook。
 */
export function useTables(connectionId: string | null, enabled = true) {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["tables", connectionId],
    queryFn: () => connectionId ? getTables(connectionId) : Promise.resolve({ tables: [] }),
    enabled: enabled && !!connectionId,
    staleTime: 60 * 1000, // 1 分钟
  });

  return {
    tables: data?.tables ?? [],
    isLoading,
    error,
    refetch,
  };
}

/**
 * 获取表结构的 hook。
 */
export function useTableSchema(
  connectionId: string | null,
  tableName: string | null,
  enabled = true
) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["table-schema", connectionId, tableName],
    queryFn: () =>
      connectionId && tableName
        ? getTableSchema(connectionId, tableName)
        : Promise.resolve({ columns: [] }),
    enabled: enabled && !!connectionId && !!tableName,
    staleTime: 60 * 1000,
  });

  return {
    columns: data?.columns ?? [],
    isLoading,
    error,
  };
}

/**
 * 预览表数据的 mutation。
 */
export function usePreviewTable() {
  const { mutateAsync, isPending, error } = useMutation({
    mutationFn: ({
      connectionId,
      tableName,
      limit,
    }: {
      connectionId: string;
      tableName: string;
      limit?: number;
    }) => previewTable(connectionId, tableName, limit),
  });

  return {
    previewTable: mutateAsync,
    isPending,
    error,
  };
}

/**
 * 验证SQL的 mutation。
 */
export function useValidateSQL(threadId: string) {
  const { mutateAsync, isPending, error, data } = useMutation({
    mutationFn: (request: ValidateSQLRequest) => validateSQL(threadId, request),
  });

  return {
    validateSQL: mutateAsync,
    isValidating: isPending,
    error,
    validationResult: data,
  };
}

/**
 * 预览节点输出的 mutation。
 */
export function usePreviewNodeOutput(threadId: string) {
  const { mutateAsync, isPending, error } = useMutation({
    mutationFn: (nodeId: string) => previewNodeOutput(threadId, nodeId, 100),
  });

  return {
    previewNode: mutateAsync,
    isPending,
    error,
  };
}

/**
 * 停止Canvas执行的 mutation。
 */
export function useStopCanvas(threadId: string) {
  const queryClient = useQueryClient();

  const { mutate, mutateAsync, isPending, error } = useMutation({
    mutationFn: () => stopCanvasExecution(threadId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["canvas-status", threadId] });
    },
  });

  return {
    stopCanvas: mutate,
    stopCanvasAsync: mutateAsync,
    isStopping: isPending,
    error,
  };
}
