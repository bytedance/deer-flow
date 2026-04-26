/**
 * Canvas 数据类型定义，用于数据分析 DAG。
 */

import type { Node, Edge } from "@xyflow/react";

// 节点类型
export type NodeType = "data_source" | "sql_executor" | "python_script" | "data_output";

// Canvas 状态
export type CanvasStatus = "idle" | "running" | "paused" | "completed" | "failed";

// Agent 执行模式
export type AgentExecutionMode = "interactive" | "readonly";

// Data Source 节点数据
export interface DataSourceNodeData {
  table_name?: string;
  db_connection_id?: string;
  [key: string]: unknown;
}

// SQL Executor 节点数据
export interface SQLExecutorNodeData {
  query_name?: string;
  sql_query?: string;
  [key: string]: unknown;
}

// Python Script 节点数据
export interface PythonScriptNodeData {
  script_name?: string;
  code?: string;
  [key: string]: unknown;
}

// Data Output 节点数据
export interface DataOutputNodeData {
  output_name?: string;
  output_type?: string;
  [key: string]: unknown;
}

// 所有节点数据的联合类型
export type CanvasNodeData =
  | DataSourceNodeData
  | SQLExecutorNodeData
  | PythonScriptNodeData
  | DataOutputNodeData;

// Canvas 节点 - 扩展 React Flow 的 Node 类型
export type CanvasNode = Node<CanvasNodeData, NodeType>;

// Canvas 边 - 扩展 React Flow 的 Edge 类型
export type CanvasEdge = Edge;

// 执行日志条目
export interface ExecutionLogEntry {
  node_id: string;
  started_at: string;
  completed_at: string | null;
  success: boolean;
  output_table: string | null;
  output_file: string | null;
  rows_affected: number;
  error: string | null;
  logs: string[];
}

// 节点执行结果
export interface NodeResult {
  success: boolean;
  output_table: string | null;
  output_file: string | null;
  rows_affected: number;
  error: string | null;
  logs: string[];
}

// Canvas
export interface Canvas {
  id: string;
  thread_id: string;
  name: string;
  description: string;
  agent_execution_mode: AgentExecutionMode;
  nodes: CanvasNode[];
  edges: CanvasEdge[];
  status: CanvasStatus;
  execution_log: ExecutionLogEntry[];
  created_at: string;
  updated_at: string;
}

// 组件信息
export interface ComponentInfo {
  type: string;
  name: string;
  description: string;
  config_schema: Record<string, unknown>;
}

// 执行状态响应
export interface ExecutionStatusResponse {
  canvas_id: string;
  status: CanvasStatus;
  current_node: string | null;
  completed_nodes: string[];
  pending_nodes: string[];
  results: Record<string, NodeResult>;
}

// API 响应类型
export interface CanvasResponse {
  id: string;
  thread_id: string;
  name: string;
  description: string;
  agent_execution_mode: AgentExecutionMode;
  nodes: CanvasNode[];
  edges: CanvasEdge[];
  status: CanvasStatus;
  execution_log: ExecutionLogEntry[];
  created_at?: string;
  updated_at?: string;
}

export interface CanvasUpdateRequest {
  name?: string;
  description?: string;
  agent_execution_mode?: AgentExecutionMode;
  nodes?: CanvasNode[];
  edges?: CanvasEdge[];
}

export interface CanvasExecuteRequest {
  db_connections?: Record<string, unknown>;
}

export interface ComponentsListResponse {
  components: ComponentInfo[];
}
