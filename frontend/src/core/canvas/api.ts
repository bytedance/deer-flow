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
  DbConnectionsListResponse,
  ExecutionStatusResponse,
  NodePreviewResponse,
  TablesListResponse,
  TablePreviewResponse,
  TableSchemaResponse,
  ValidateSQLRequest,
  ValidateSQLResponse,
} from "./types";

/**
 * 获取API基础URL。
 */
function getBaseUrl(): string {
  return env.NEXT_PUBLIC_BACKEND_BASE_URL ?? "";
}

/**
 * 获取线程的 canvas。
 */
export async function getCanvas(threadId: string): Promise<Canvas | null> {
  const response = await fetch(
    `${getBaseUrl()}/api/threads/${threadId}/canvas`,
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
    `${getBaseUrl()}/api/threads/${threadId}/canvas`,
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
    `${getBaseUrl()}/api/threads/${threadId}/canvas/execute`,
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
    `${getBaseUrl()}/api/threads/${threadId}/canvas/status`,
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
    `${getBaseUrl()}/api/threads/${threadId}/canvas`,
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
    `${getBaseUrl()}/api/canvas/components`,
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

/**
 * 获取可用的数据库连接。
 */
export async function getDbConnections(): Promise<DbConnectionsListResponse> {
  const response = await fetch(`${getBaseUrl()}/api/db-connections`);

  if (!response.ok) {
    throw new Error(`Failed to get db connections: ${response.statusText}`);
  }

  return response.json();
}

/**
 * 获取连接的表列表。
 */
export async function getTables(connectionId: string): Promise<TablesListResponse> {
  const response = await fetch(
    `${getBaseUrl()}/api/db-connections/${connectionId}/tables`
  );

  if (!response.ok) {
    throw new Error(`Failed to get tables: ${response.statusText}`);
  }

  return response.json();
}

/**
 * 获取表结构。
 */
export async function getTableSchema(
  connectionId: string,
  tableName: string
): Promise<TableSchemaResponse> {
  const response = await fetch(
    `${getBaseUrl()}/api/db-connections/${connectionId}/tables/${tableName}/schema`
  );

  if (!response.ok) {
    throw new Error(`Failed to get table schema: ${response.statusText}`);
  }

  return response.json();
}

/**
 * 预览表数据。
 */
export async function previewTable(
  connectionId: string,
  tableName: string,
  limit = 100
): Promise<TablePreviewResponse> {
  const response = await fetch(
    `${getBaseUrl()}/api/db-connections/${connectionId}/tables/${tableName}/preview?limit=${limit}`
  );

  if (!response.ok) {
    throw new Error(`Failed to preview table: ${response.statusText}`);
  }

  return response.json();
}

/**
 * 验证SQL。
 */
export async function validateSQL(
  threadId: string,
  request: ValidateSQLRequest
): Promise<ValidateSQLResponse> {
  const response = await fetch(
    `${getBaseUrl()}/api/threads/${threadId}/canvas/validate-sql`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(request),
    }
  );

  if (!response.ok) {
    throw new Error(`Failed to validate SQL: ${response.statusText}`);
  }

  return response.json();
}

/**
 * 预览节点输出。
 */
export async function previewNodeOutput(
  threadId: string,
  nodeId: string,
  limit = 100
): Promise<NodePreviewResponse> {
  const response = await fetch(
    `${getBaseUrl()}/api/threads/${threadId}/canvas/nodes/${nodeId}/preview?limit=${limit}`
  );

  if (!response.ok) {
    throw new Error(`Failed to preview node output: ${response.statusText}`);
  }

  return response.json();
}

/**
 * 停止Canvas执行。
 */
export async function stopCanvasExecution(threadId: string): Promise<void> {
  const response = await fetch(
    `${getBaseUrl()}/api/threads/${threadId}/canvas/stop`,
    {
      method: "POST",
    }
  );

  if (!response.ok) {
    throw new Error(`Failed to stop canvas: ${response.statusText}`);
  }
}
