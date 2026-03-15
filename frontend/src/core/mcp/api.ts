import { apiFetch, apiJson } from "@/core/api/fetch";

import type { MCPConfig } from "./types";

export async function loadMCPConfig() {
  return apiJson<MCPConfig>("/api/mcp/config");
}

export async function updateMCPConfig(config: MCPConfig) {
  const res = await apiFetch("/api/mcp/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
  return res.json();
}
