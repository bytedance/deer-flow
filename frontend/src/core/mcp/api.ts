import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type { MCPConfig } from "./types";

export async function loadMCPConfig() {
  const response = await fetch(`${getBackendBaseURL()}/api/mcp/config`);
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
  return response.json();
}

export interface OAuthPresetInfo {
  id: string;
  displayName: string;
  description: string;
  provider: string;
  configured: boolean;
}

export async function listOAuthPresets(): Promise<OAuthPresetInfo[]> {
  const response = await fetch(`${getBackendBaseURL()}/api/mcp/oauth/presets`);
  if (!response.ok) {
    throw new Error(`Failed to load OAuth presets: ${response.status}`);
  }
  const data = (await response.json()) as { presets: OAuthPresetInfo[] };
  return data.presets;
}

export interface StartOAuthResponse {
  authorization_url: string;
  state: string;
}

export async function startOAuthFlow(
  presetId: string,
): Promise<StartOAuthResponse> {
  const response = await fetch(`${getBackendBaseURL()}/api/mcp/oauth/start`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ preset_id: presetId }),
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Failed to start OAuth flow: ${text}`);
  }
  return (await response.json()) as StartOAuthResponse;
}

export interface McpServerTestResult {
  ok: boolean;
  tool_count: number | null;
  tool_names: string[];
  error: string | null;
}

export async function testMCPServer(
  serverName: string,
): Promise<McpServerTestResult> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/mcp/servers/${encodeURIComponent(serverName)}/test`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
    },
  );
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Test Connection failed: ${text}`);
  }
  return (await response.json()) as McpServerTestResult;
}
