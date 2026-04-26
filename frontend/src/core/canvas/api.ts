/**
 * Canvas API 客户端，用于 canvas 操作。
 */

import { env } from "@/env";

import type {
  Canvas,
  CanvasExecuteRequest,
  CanvasResponse,
  CanvasUpdateRequest,
  ComponentsListResponse,
  ExecutionStatusResponse,
} from "./types";

/**
 * 获取线程的 canvas。
 */
export async function getCanvas(threadId: string): Promise<Canvas | null> {
  const response = await fetch(
    `${env.NEXT_PUBLIC_BACKEND_BASE_URL}/api/threads/${threadId}/canvas`,
  );

  if (response.status === 404) {
    return null;
  }

  if (!response.ok) {
    throw new Error(`Failed to get canvas: ${response.statusText}`);
  }

  const data: CanvasResponse = await response.json();
  return mapCanvasResponse(data);
}

/**
 * 更新或创建线程的 canvas。
 */
export async function updateCanvas(
  threadId: string,
  request: CanvasUpdateRequest,
): Promise<Canvas> {
  const response = await fetch(
    `${env.NEXT_PUBLIC_BACKEND_BASE_URL}/api/threads/${threadId}/canvas`,
    {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(request),
    },
  );

  if (!response.ok) {
    throw new Error(`Failed to update canvas: ${response.statusText}`);
  }

  const data: CanvasResponse = await response.json();
  return mapCanvasResponse(data);
}

/**
 * 执行 canvas DAG。
 */
export async function executeCanvas(
  threadId: string,
  request: CanvasExecuteRequest = {},
): Promise<ExecutionStatusResponse> {
  const response = await fetch(
    `${env.NEXT_PUBLIC_BACKEND_BASE_URL}/api/threads/${threadId}/canvas/execute`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(request),
    },
  );

  if (!response.ok) {
    throw new Error(`Failed to execute canvas: ${response.statusText}`);
  }

  return response.json();
}

/**
 * 获取 canvas 执行状态。
 */
export async function getExecutionStatus(
  threadId: string,
): Promise<ExecutionStatusResponse> {
  const response = await fetch(
    `${env.NEXT_PUBLIC_BACKEND_BASE_URL}/api/threads/${threadId}/canvas/status`,
  );

  if (!response.ok) {
    throw new Error(`Failed to get execution status: ${response.statusText}`);
  }

  return response.json();
}

/**
 * 删除线程的 canvas。
 */
export async function deleteCanvas(threadId: string): Promise<void> {
  const response = await fetch(
    `${env.NEXT_PUBLIC_BACKEND_BASE_URL}/api/threads/${threadId}/canvas`,
    {
      method: "DELETE",
    },
  );

  if (!response.ok) {
    throw new Error(`Failed to delete canvas: ${response.statusText}`);
  }
}

/**
 * 获取可用组件。
 */
export async function getComponents(): Promise<ComponentsListResponse> {
  const response = await fetch(
    `${env.NEXT_PUBLIC_BACKEND_BASE_URL}/api/canvas/components`,
  );

  if (!response.ok) {
    throw new Error(`Failed to get components: ${response.statusText}`);
  }

  return response.json();
}

/**
 * 将 CanvasResponse 映射为 Canvas。
 */
function mapCanvasResponse(response: CanvasResponse): Canvas {
  return {
    ...response,
    created_at: response.created_at ?? new Date().toISOString(),
    updated_at: response.updated_at ?? new Date().toISOString(),
  };
}
