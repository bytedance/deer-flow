import { throwGatewayApiError } from "@/core/api/errors";
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type {
  AgentTracing,
  SaveAgentTracingRequest,
  SaveTracingProfileRequest,
  TracingProfile,
  TracingProfilesResponse,
} from "./types";

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${getBackendBaseURL()}/api${path}`, init);
  if (!response.ok)
    await throwGatewayApiError(response, "Tracing request failed");
  return response.json() as Promise<T>;
}

export const loadTracingProfiles = (signal?: AbortSignal) =>
  request<TracingProfilesResponse>("/tracing/profiles", { signal });

export const loadAgentTracing = (name: string, signal?: AbortSignal) =>
  request<AgentTracing>(`/agents/${encodeURIComponent(name)}/tracing`, {
    signal,
  });

export const saveAgentTracing = (name: string, body: SaveAgentTracingRequest) =>
  request<AgentTracing>(`/agents/${encodeURIComponent(name)}/tracing`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const saveTracingProfile = (
  id: string | null,
  body: SaveTracingProfileRequest,
) =>
  request<TracingProfile>(
    `/tracing/profiles${id ? `/${encodeURIComponent(id)}` : ""}`,
    {
      method: id ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
