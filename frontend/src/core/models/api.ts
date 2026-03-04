import { authFetch } from "@/core/auth/fetch";

import { getBackendBaseURL } from "../config";

import type { ProviderId, ProviderModel } from "./types";

export async function loadProviderModels(provider: ProviderId) {
  const res = await authFetch(`${getBackendBaseURL()}/api/providers/${provider}/models`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  if (!res.ok) {
    throw new Error(`Failed to load ${provider} models (${res.status})`);
  }
  const data = (await res.json()) as { provider: ProviderId; models: ProviderModel[] };
  return data;
}

export async function validateProviderKey(provider: ProviderId) {
  const res = await authFetch(`${getBackendBaseURL()}/api/providers/${provider}/validate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  if (!res.ok) {
    throw new Error(`Failed to validate ${provider} API key (${res.status})`);
  }
  return (await res.json()) as {
    provider: ProviderId;
    valid: boolean;
    message: string;
  };
}

export async function getProviderKeyStatus(provider: ProviderId) {
  const res = await authFetch(`${getBackendBaseURL()}/api/providers/${provider}/key`);
  if (!res.ok) {
    throw new Error(`Failed to load ${provider} key status (${res.status})`);
  }
  return (await res.json()) as { provider: ProviderId; has_key: boolean };
}

export async function setProviderKey(provider: ProviderId, apiKey: string) {
  const res = await authFetch(`${getBackendBaseURL()}/api/providers/${provider}/key`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ api_key: apiKey }),
  });
  if (!res.ok) {
    const detail = await res.json().then((b) => b.detail).catch(() => undefined);
    throw new Error(detail ?? `Failed to store ${provider} API key (${res.status})`);
  }
  return (await res.json()) as { provider: ProviderId; has_key: boolean };
}

export async function deleteProviderKey(provider: ProviderId) {
  const res = await authFetch(`${getBackendBaseURL()}/api/providers/${provider}/key`, {
    method: "DELETE",
  });
  if (!res.ok) {
    throw new Error(`Failed to remove ${provider} API key (${res.status})`);
  }
  return (await res.json()) as { provider: ProviderId; has_key: boolean };
}
