import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type {
  ConnectorConnection,
  ConnectorConnectionsResponse,
  ConnectorProvider,
  ConnectorProvidersResponse,
} from "./types";

function connectorUrl(path: string): string {
  return `${getBackendBaseURL()}/api/connector${path}`;
}

export async function listProviders(): Promise<ConnectorProvider[]> {
  const response = await fetch(connectorUrl("/providers"));
  if (!response.ok) {
    throw new Error(
      `Failed to load connector providers: ${response.statusText}`,
    );
  }
  const data = (await response.json()) as ConnectorProvidersResponse;
  return data.providers ?? [];
}

export async function getProvider(service: string): Promise<ConnectorProvider> {
  const response = await fetch(
    connectorUrl(`/providers/${encodeURIComponent(service)}`),
  );
  if (!response.ok) {
    throw new Error(
      `Failed to load provider ${service}: ${response.statusText}`,
    );
  }
  return response.json() as Promise<ConnectorProvider>;
}

export async function listConnections(): Promise<ConnectorConnection[]> {
  const response = await fetch(connectorUrl("/connections"));
  if (!response.ok) {
    throw new Error(`Failed to load connections: ${response.statusText}`);
  }
  const data = (await response.json()) as ConnectorConnectionsResponse;
  return data.connections ?? [];
}

export async function upsertConnection(
  service: string,
  body: Record<string, unknown>,
): Promise<void> {
  const response = await fetch(
    connectorUrl(`/connections/${encodeURIComponent(service)}`),
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  if (!response.ok) {
    throw new Error(
      `Failed to save connection for ${service}: ${response.statusText}`,
    );
  }
}

export async function deleteConnection(service: string): Promise<void> {
  const response = await fetch(
    connectorUrl(`/connections/${encodeURIComponent(service)}`),
    {
      method: "DELETE",
    },
  );
  if (!response.ok) {
    throw new Error(`Failed to disconnect ${service}: ${response.statusText}`);
  }
}

export async function oauthAuthorize(
  service: string,
): Promise<{ url: string }> {
  const response = await fetch(connectorUrl("/oauth/authorize"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ service }),
  });
  if (!response.ok) {
    throw new Error(
      `Failed to start OAuth for ${service}: ${response.statusText}`,
    );
  }
  const data = (await response.json()) as {
    authorizationUrl?: string;
    url?: string;
  };
  return { url: data.authorizationUrl ?? data.url ?? "" };
}
