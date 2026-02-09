// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { getAuthHeaders } from "../auth/utils";

import { resolveServiceURL } from "./resolve-service-url";

export interface AdminConfig {
  tavilyApiKey: string;
  braveSearchApiKey: string;
  volcengineTtsAppId: string;
  ragflowApiKey: string;
}

const DEFAULT_ADMIN_CONFIG: AdminConfig = {
  tavilyApiKey: "",
  braveSearchApiKey: "",
  volcengineTtsAppId: "",
  ragflowApiKey: "",
};

function normalizeConfig(data: Partial<Record<string, string>> | null | undefined): AdminConfig {
  if (!data) {
    return { ...DEFAULT_ADMIN_CONFIG };
  }

  return {
    tavilyApiKey: data.tavilyApiKey ?? data.tavily_api_key ?? "",
    braveSearchApiKey: data.braveSearchApiKey ?? data.brave_search_api_key ?? "",
    volcengineTtsAppId: data.volcengineTtsAppId ?? data.volcengine_tts_app_id ?? "",
    ragflowApiKey: data.ragflowApiKey ?? data.ragflow_api_key ?? "",
  };
}

export async function fetchAdminConfig(): Promise<AdminConfig> {
  const response = await fetch(resolveServiceURL("admin/config"), {
    method: "GET",
    headers: getAuthHeaders(),
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(`Failed to load admin configuration (${response.status})`);
  }

  const payload = (await response.json()) as Partial<Record<string, string>>;
  return normalizeConfig(payload);
}

export async function updateAdminConfig(config: AdminConfig): Promise<void> {
  const response = await fetch(resolveServiceURL("admin/config"), {
    method: "PUT",
    headers: getAuthHeaders(),
    body: JSON.stringify({
      tavily_api_key: config.tavilyApiKey,
      brave_search_api_key: config.braveSearchApiKey,
      volcengine_tts_app_id: config.volcengineTtsAppId,
      ragflow_api_key: config.ragflowApiKey,
    }),
  });

  if (!response.ok) {
    const message = await safeReadError(response);
    throw new Error(message ?? `Failed to save admin configuration (${response.status})`);
  }
}

async function safeReadError(response: Response): Promise<string | null> {
  try {
    const payload = await response.json();
    if (typeof payload?.detail === "string") {
      return payload.detail;
    }
    if (typeof payload?.message === "string") {
      return payload.message;
    }
  } catch {
    // ignore
  }
  return null;
}

export const __internal = {
  normalizeConfig,
};
