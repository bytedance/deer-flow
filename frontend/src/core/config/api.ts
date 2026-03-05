import { env } from "@/env";

export interface AppBrandConfig {
  name: string;
  website_url?: string | null;
  github_url?: string | null;
  support_email?: string | null;
}

export interface AppConfigResponse {
  brand: AppBrandConfig;
}

function getBackendBaseURLForConfig() {
  const base = env.VITE_BACKEND_BASE_URL?.trim();
  if (!base) {
    return "";
  }
  const normalized = base.replace(/\/+$/, "");
  if (normalized.endsWith("/api")) {
    return normalized.slice(0, -4);
  }
  return normalized;
}

export async function loadAppConfig(): Promise<AppConfigResponse | null> {
  try {
    const response = await fetch(`${getBackendBaseURLForConfig()}/api/config`);
    if (!response.ok) {
      return null;
    }
    return (await response.json()) as AppConfigResponse;
  } catch {
    return null;
  }
}
