import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type { MCPConfig, MCPServerConfig } from "./types";

export class MCPConfigRequestError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "MCPConfigRequestError";
    this.status = status;
  }
  get isAdminRequired(): boolean {
    return this.status === 403;
  }
}

async function readErrorDetail(
  response: Response,
  fallback: string,
): Promise<string> {
  const error = (await response.json().catch(() => ({}))) as {
    detail?: unknown;
  };
  return typeof error.detail === "string" ? error.detail : fallback;
}

export async function loadMCPConfig() {
  const response = await fetch(`${getBackendBaseURL()}/api/mcp/config`);
  if (!response.ok) {
    throw new MCPConfigRequestError(
      response.status,
      await readErrorDetail(response, "Failed to load MCP configuration"),
    );
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
    throw new MCPConfigRequestError(
      response.status,
      await readErrorDetail(response, "Failed to update MCP configuration"),
    );
  }
  return response.json();
}

async function mutateMCPServerConfig(
  path: string,
  method: "POST" | "PUT" | "DELETE",
  body: unknown,
  fallback: string,
) {
  const response = await fetch(`${getBackendBaseURL()}${path}`, {
    method,
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new MCPConfigRequestError(
      response.status,
      await readErrorDetail(response, fallback),
    );
  }
  return response.json() as Promise<MCPConfig>;
}

export function createMCPServers(servers: Record<string, MCPServerConfig>) {
  return mutateMCPServerConfig(
    "/api/mcp/config/servers",
    "POST",
    { mcp_servers: servers },
    "Failed to add MCP servers",
  );
}

export function updateMCPServer(serverName: string, server: MCPServerConfig) {
  return mutateMCPServerConfig(
    "/api/mcp/config/server",
    "PUT",
    { server_name: serverName, server },
    "Failed to update MCP server",
  );
}

export function deleteMCPServer(serverName: string) {
  return mutateMCPServerConfig(
    "/api/mcp/config/server",
    "DELETE",
    { server_name: serverName },
    "Failed to delete MCP server",
  );
}

export async function updateMCPServerState(
  serverName: string,
  enabled: boolean,
) {
  const response = await fetch(`${getBackendBaseURL()}/api/mcp/config`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      server_name: serverName,
      enabled,
    }),
  });
  if (!response.ok) {
    throw new MCPConfigRequestError(
      response.status,
      await readErrorDetail(response, "Failed to update MCP server"),
    );
  }
  return response.json() as Promise<MCPConfig>;
}
