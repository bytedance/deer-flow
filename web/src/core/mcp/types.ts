// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

export interface MCPToolMetadata {
  name: string;
  description: string;
  inputSchema?: Record<string, unknown>;
}

export interface GenericMCPServerMetadata<T extends string> {
  name: string;
  transport: T;
  enabled: boolean;
  env?: Record<string, string>;
  tools: MCPToolMetadata[];
  createdAt: number;
  updatedAt: number;
}

export interface StdioMCPServerMetadata
  extends GenericMCPServerMetadata<"stdio"> {
  transport: "stdio";
  command: string;
  args?: string[];
}
export type SimpleStdioMCPServerMetadata = Omit<
  StdioMCPServerMetadata,
  "enabled" | "tools" | "createdAt" | "updatedAt"
>;

export interface SSEMCPServerMetadata extends GenericMCPServerMetadata<"sse"|"streamable_http"> {
  transport: "sse"|"streamable_http"
  url: string;
}

export type SimpleSSEMCPServerMetadata = Omit<
  SSEMCPServerMetadata,
  "enabled" | "tools" | "createdAt" | "updatedAt"
>;

export type MCPServerMetadata = StdioMCPServerMetadata | SSEMCPServerMetadata;
export type SimpleMCPServerMetadata =
  | SimpleStdioMCPServerMetadata
  | SimpleSSEMCPServerMetadata;
