import { getBackendBaseURL } from "@/core/config";

import type { MCPConfig, MCPToolsResponse } from "./types";

export async function loadMCPConfig() {
  const response = await fetch(`${getBackendBaseURL()}/api/mcp/config`);
  if (!response.ok) {
    const err = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(err.detail ?? `Failed to load MCP config: ${response.statusText}`);
  }
  return response.json() as Promise<MCPConfig>;
}

export async function updateMCPConfig(config: MCPConfig) {
  const response = await fetch(`${getBackendBaseURL()}/api/mcp/config`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(config),
  });
  if (!response.ok) {
    const err = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(err.detail ?? `Failed to update MCP config: ${response.statusText}`);
  }
  return response.json();
}

export async function loadMCPServerTools() {
  const response = await fetch(`${getBackendBaseURL()}/api/mcp/tools`);
  if (!response.ok) {
    const err = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(err.detail ?? `Failed to load MCP server tools: ${response.statusText}`);
  }
  return response.json() as Promise<MCPToolsResponse>;
}
