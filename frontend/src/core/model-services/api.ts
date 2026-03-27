import { getBackendBaseURL } from "@/core/config";
import { env } from "@/env";

import type {
  DiscoveredProviderModelsResponse,
  ModelServiceDefaults,
  ModelServiceProvider,
  ModelServicesConfig,
  ModelServicesConfigWrite,
  ProviderTestResult,
} from "./types";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const base =
    env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true"
      ? `${window.location.origin}/mock/api/model-services`
      : `${getBackendBaseURL()}/api/model-services`;
  const response = await fetch(`${base}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    const text = await response.text();
    let message = text || `Request failed: ${response.status}`;
    try {
      const payload = JSON.parse(text) as { detail?: string };
      message = payload.detail ?? message;
    } catch {
      // Ignore JSON parsing errors and fall back to the raw response text.
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export async function loadModelServicesConfig() {
  return apiFetch<ModelServicesConfig>("");
}

export async function updateModelServicesConfig(config: ModelServicesConfigWrite) {
  return apiFetch<ModelServicesConfig>("", {
    method: "PUT",
    body: JSON.stringify(config),
  });
}

export async function testModelServiceProvider(providerId: string) {
  return apiFetch<ProviderTestResult>(`/providers/${providerId}/test`, {
    method: "POST",
  });
}

export async function syncModelServiceProvider(providerId: string) {
  return apiFetch<ModelServiceProvider>(`/providers/${providerId}/sync-models`, {
    method: "POST",
  });
}

export async function discoverModelServiceProvider(providerId: string) {
  return apiFetch<DiscoveredProviderModelsResponse>(
    `/providers/${providerId}/discover-models`,
    {
      method: "POST",
    },
  );
}

export async function updateModelServiceDefaults(defaults: ModelServiceDefaults) {
  return apiFetch<ModelServicesConfig>("/defaults", {
    method: "PATCH",
    body: JSON.stringify(defaults),
  });
}
