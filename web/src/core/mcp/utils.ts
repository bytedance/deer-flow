// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { useSettingsStore } from "../store";

/**
 * 解析工具名称，提取服务器名称和实际工具名称
 */
export function parseToolName(fullToolName: string): { serverName?: string; toolName: string } {
  if (fullToolName.includes('_')) {
    const parts = fullToolName.split('_');
    return {
      serverName: parts[0],
      toolName: parts.slice(1).join('_')
    };
  }
  return { toolName: fullToolName };
}

/**
 * 格式化工具显示名称
 */
export function formatToolDisplayName(fullToolName: string): string {
  const { toolName } = parseToolName(fullToolName);
  return toolName.replace(/^mcp_/, "");
}

export function findMCPTool(name: string) {
  const mcpServers = useSettingsStore.getState().mcp.servers;
  
  // First try exact match
  for (const server of mcpServers) {
    for (const tool of server.tools) {
      if (tool.name === name) {
        return tool;
      }
    }
  }
  
  // If no exact match and name contains underscore, try matching without server prefix
  if (name.includes('_')) {
    const toolNameWithoutPrefix = name.substring(name.indexOf('_') + 1);
    for (const server of mcpServers) {
      for (const tool of server.tools) {
        if (tool.name === toolNameWithoutPrefix) {
          return {
            ...tool,
            name: name, // Return with the prefixed name
            description: `[${server.name}] ${tool.description}`
          };
        }
      }
    }
  }
  
  return null;
}
