import { getBackendBaseURL } from "@/core/config";

import type { MCPConfig, MCPConfigUpdate } from "./types";

export async function loadMCPConfig() {
  const response = await fetch(`${getBackendBaseURL()}/api/mcp/config`);
  if (!response.ok) {
    throw new Error("Failed to load MCP configuration");
  }
  return response.json() as Promise<MCPConfig>;
}

export async function updateMCPConfig(config: MCPConfigUpdate) {
  const response = await fetch(`${getBackendBaseURL()}/api/mcp/config`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(config),
  });
  if (!response.ok) {
    throw new Error("Failed to update MCP configuration");
  }
  return response.json() as Promise<MCPConfig>;
}
