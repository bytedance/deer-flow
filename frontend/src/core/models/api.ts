import { authFetch } from "@/core/auth/fetch";

import { getBackendBaseURL } from "../config";

import type { ProviderCatalog, ProviderId, ProviderModel } from "./types";

export async function loadProviderCatalog() {
  const res = await authFetch(`${getBackendBaseURL()}/api/providers/catalog`);
  if (!res.ok) {
    throw new Error(`Failed to load provider catalog (${res.status})`);
  }
  return (await res.json()) as { providers: ProviderCatalog[] };
}

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

export async function getUserModelPreferences() {
  const res = await authFetch(`${getBackendBaseURL()}/api/user/preferences/models`);
  if (!res.ok) {
    throw new Error(`Failed to load user model preferences (${res.status})`);
  }
  return (await res.json()) as {
    model_name?: string | null;
    thinking_effort?: string | null;
    provider_enabled?: Record<string, boolean> | null;
    enabled_models?: Record<string, boolean> | null;
    updated_at?: string | null;
  };
}

export async function setUserModelPreferences(payload: {
  model_name?: string | null;
  thinking_effort?: string | null;
  provider_enabled?: Record<string, boolean> | null;
  enabled_models?: Record<string, boolean> | null;
}) {
  const res = await authFetch(`${getBackendBaseURL()}/api/user/preferences/models`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const detail = await res.json().then((body) => body.detail).catch(() => undefined);
    throw new Error(detail ?? `Failed to save user model preferences (${res.status})`);
  }
  return (await res.json()) as {
    model_name?: string | null;
    thinking_effort?: string | null;
    provider_enabled?: Record<string, boolean> | null;
    enabled_models?: Record<string, boolean> | null;
    updated_at?: string | null;
  };
}
