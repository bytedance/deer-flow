import { z } from "zod";

import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

const path = "/api/mcp/user-oauth";

const connectionsResponse = z.object({
  connections: z.array(
    z.object({
      server_key: z.string(),
      display_name: z.string(),
      status: z.enum([
        "disconnected",
        "connected",
        "reconnect_required",
        "unavailable",
        "removed",
      ]),
    }),
  ),
});

export async function loadMCPUserConnections(signal: AbortSignal) {
  const response = await fetch(`${getBackendBaseURL()}${path}`, { signal });
  // Auth-disabled deployments cannot establish user grants. An older Gateway
  // might also lack this optional surface.
  if (response.status === 403 || response.status === 404) return [];
  if (!response.ok) throw new Error("Could not load MCP connections");
  return connectionsResponse.parse(await response.json()).connections;
}

export async function changeMCPUserConnection(
  serverKey: string,
  action: "connect" | "disconnect",
) {
  const connect = action === "connect";
  const connectionURL = `${getBackendBaseURL()}${path}/${encodeURIComponent(serverKey)}`;
  const response = await fetch(
    connect ? `${connectionURL}/connect` : connectionURL,
    {
      method: connect ? "POST" : "DELETE",
    },
  );
  if (!response.ok) throw new Error("Could not change MCP connection");
  if (!connect) return;
  const result = (await response.json()) as { authorization_url?: unknown };
  if (typeof result.authorization_url !== "string") {
    throw new Error("Missing MCP authorization URL");
  }
  const url = new URL(result.authorization_url);
  if (url.protocol !== "https:" || url.username || url.password) {
    throw new Error("Invalid MCP authorization URL");
  }
  return url.href;
}
